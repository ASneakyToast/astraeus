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

from typing import Annotated, Any, Union

import pydantic
from pydantic import Field, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from starlette_cms.fields import (
    BlockField,
    ImageField,
    ListField,
    RichTextField,
    TextField,
    _BaseField,
)


def _make_field(
    annotation: Any,
    default: Any,
    field_meta: dict[str, Any],
) -> tuple[Any, FieldInfo]:
    """
    Convert a (annotation, _BaseField default) pair into a (type, FieldInfo) tuple
    suitable for ``pydantic.create_model``.

    :param annotation: The raw type annotation from the class (may be ``str``, ``dict``, etc.)
    :param default: The _BaseField instance used as the class attribute default.
    :param field_meta: Pre-computed field_meta dict from the field instance.
    """
    # Build the json_schema_extra dict; None means "no extra" (omit from schema)
    extra: dict[str, Any] | None = {"cms:field_meta": field_meta} if field_meta else None

    optional = not getattr(default, "required", False)

    if isinstance(default, TextField):
        if optional:
            return (str | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value]
        return (str, Field(..., json_schema_extra=extra))  # type: ignore[return-value]

    if isinstance(default, RichTextField):
        if optional:
            return (dict | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value]
        return (dict, Field(..., json_schema_extra=extra))  # type: ignore[return-value]

    if isinstance(default, ImageField):
        if optional:
            return (str | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value]
        return (str, Field(..., json_schema_extra=extra))  # type: ignore[return-value]

    if isinstance(default, ListField):
        if default.blocks:
            # Polymorphic block list — discriminated union
            union_type: Any = Union[tuple(default.blocks)]  # type: ignore[arg-type]  # noqa: UP007
            item_ann = Annotated[union_type, Field(discriminator="block_type")]
            list_type: Any = list[item_ann]  # type: ignore[valid-type]
        elif default.item_type is not None:
            list_type = list[default.item_type]  # type: ignore[valid-type]
        else:
            list_type = list[Any]

        if optional:
            return (list_type | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value]
        return (list_type, Field(default_factory=list, json_schema_extra=extra))  # type: ignore[return-value]

    if isinstance(default, BlockField):
        block_cls = default.block_type
        if block_cls is None:
            # Use the annotation type only when it's a concrete model class.
            # `hero: dict = BlockField(required=False)` → fall back to dict.
            # `hero: HeroModel = BlockField(...)` → use HeroModel.
            _scalar_types = (str, int, float, bool, dict, list)
            if isinstance(annotation, type) and annotation not in _scalar_types:
                block_cls = annotation
            else:
                block_cls = dict
        if optional:
            return (block_cls | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value, operator]
        return (block_cls, Field(..., json_schema_extra=extra))  # type: ignore[return-value]

    # Fallback: use annotation as-is
    fallback_type: Any = annotation if annotation is not None else Any
    if optional:
        return (fallback_type | None, Field(default=None, json_schema_extra=extra))  # type: ignore[return-value]
    return (fallback_type, Field(..., json_schema_extra=extra))  # type: ignore[return-value]


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
    model.model_rebuild()
    return model
