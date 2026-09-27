"""
Pydantic model generation from annotated block/document classes.

Converts plain annotated classes (using _BaseField instances as defaults)
into fully validated Pydantic BaseModel subclasses. Adds a ``block_type``
discriminator literal for blocks, and a ``__document_type__`` marker for
documents.

Usage::

    from starlette_cms.model_builder import build_block_model, build_document_model

    class HeroBlock:
        title: str = TextField(required=True)

    HeroModel = build_block_model("hero", HeroBlock)
    # HeroModel is now a Pydantic model with block_type: Literal["hero"] = "hero"
"""

from __future__ import annotations

from typing import Any

import pydantic
from pydantic import Field, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from starlette_cms.fields import DocumentRef, ImageField, _BaseField


def _make_field(
    annotation: Any,
    default: _BaseField,
    field_meta: dict[str, Any],
) -> tuple[Any, FieldInfo]:
    """
    Convert a (annotation, _BaseField default) pair into a (type, FieldInfo) tuple
    suitable for ``pydantic.create_model``.

    Delegates entirely to ``default.to_pydantic()`` — every ``_BaseField``
    subclass (built-in or from a plugin) owns its own Pydantic representation
    (see fields.py), so adding a new field type never requires editing this
    function.

    :param annotation: The raw type annotation from the class (may be ``str``, ``dict``, etc.)
    :param default: The _BaseField instance used as the class attribute default.
    :param field_meta: Pre-computed field_meta dict from the field instance.
    """
    extra: dict[str, Any] | None = {"cms:field_meta": field_meta} if field_meta else None
    optional = not getattr(default, "required", False)
    py_type, kwargs = default.to_pydantic(annotation, optional)
    return (py_type, Field(json_schema_extra=extra, **kwargs))  # type: ignore[return-value]


def _collect_field_defs(cls: type) -> dict[str, tuple[Any, FieldInfo]]:
    """
    Walk ``cls.__annotations__`` and build a ``{name: (type, FieldInfo)}`` dict
    suitable for ``pydantic.create_model``.

    Uses ``typing.get_type_hints()`` to resolve stringified annotations produced
    by ``from __future__ import annotations``.

    Only processes attributes whose default value is a ``_BaseField`` instance.
    Plain annotations without a ``_BaseField`` default are passed through unchanged.
    """
    import sys
    import typing

    field_defs: dict[str, tuple[Any, FieldInfo]] = {}

    # Resolve annotations — get_type_hints() evaluates forward-reference strings
    # using the module globals where cls was defined.
    module = sys.modules.get(cls.__module__, None)
    globalns = getattr(module, "__dict__", {}) if module else {}
    try:
        resolved = typing.get_type_hints(cls, globalns=globalns, include_extras=True)
    except Exception:
        # Fall back to raw annotations if resolution fails (e.g. unknown forward refs)
        resolved = {}
        for klass in reversed(cls.__mro__):
            if klass is object:
                continue
            resolved.update(getattr(klass, "__annotations__", {}))

    for attr_name, annotation in resolved.items():
        if attr_name.startswith("_"):
            continue

        default = getattr(cls, attr_name, PydanticUndefined)

        if isinstance(default, _BaseField):
            meta = default.field_meta()
            field_defs[attr_name] = _make_field(annotation, default, meta)
        elif default is PydanticUndefined:
            # Plain annotation, no default — treat as required
            field_defs[attr_name] = (annotation, Field(...))  # type: ignore[assignment]
        else:
            # Plain default value (non-field)
            field_defs[attr_name] = (annotation, Field(default=default))  # type: ignore[assignment]

    return field_defs


def get_immutable_fields(cls: type) -> list[str]:
    """Return the list of field names that are marked ``immutable=True``."""
    result = []
    for attr_name, value in vars(cls).items():
        if isinstance(value, _BaseField) and value.immutable:
            result.append(attr_name)
    return result


def build_block_model(name: str, cls: type) -> type[pydantic.BaseModel]:
    """
    Convert a plain annotated class into a Pydantic BaseModel for use as a block.

    Injects ``block_type: Literal[name] = name`` as a discriminator field so
    ``ListField(blocks=[...])`` discriminated unions work correctly.

    :param name: The block type name string (e.g. ``"hero"``).
    :param cls: The unannotated class to convert.
    :returns: A Pydantic BaseModel subclass with ``__block_type__`` set.
    """
    from typing import Literal

    field_defs = _collect_field_defs(cls)

    # Inject discriminator field first in field ordering
    discriminator_type = Literal[name]  # type: ignore[valid-type]
    field_defs = {
        "block_type": (discriminator_type, Field(default=name)),
        **field_defs,
    }

    model = create_model(cls.__name__, **field_defs)  # type: ignore[call-overload]
    model.__block_type__ = name  # type: ignore[attr-defined]
    model.__immutable_fields__ = get_immutable_fields(cls)  # type: ignore[attr-defined]
    model.__ref_fields__ = {  # type: ignore[attr-defined]
        attr: value for attr, value in vars(cls).items() if isinstance(value, DocumentRef)
    }
    model.model_rebuild()
    return model


def build_document_model(name: str, cls: type) -> type[pydantic.BaseModel]:
    """
    Convert a plain annotated class into a Pydantic BaseModel for use as a document.

    Does NOT inject a ``block_type`` discriminator. Attaches ``__document_type__``
    to the model class.

    :param name: The document type name string (e.g. ``"page"``).
    :param cls: The unannotated class to convert.
    :returns: A Pydantic BaseModel subclass with ``__document_type__`` set.
    """
    field_defs = _collect_field_defs(cls)

    model = create_model(cls.__name__, **field_defs)  # type: ignore[call-overload]
    model.__document_type__ = name  # type: ignore[attr-defined]

    # Collect the names of all ImageField attributes so documents.py can
    # validate image keys against an optional MediaBackend without re-inspecting
    # the original class.
    model.__image_fields__ = [  # type: ignore[attr-defined]
        attr for attr, val in vars(cls).items() if isinstance(val, ImageField)
    ]

    model.__immutable_fields__ = get_immutable_fields(cls)  # type: ignore[attr-defined]
    model.__ref_fields__ = {  # type: ignore[attr-defined]
        attr: value for attr, value in vars(cls).items() if isinstance(value, DocumentRef)
    }

    model.model_rebuild()
    return model
