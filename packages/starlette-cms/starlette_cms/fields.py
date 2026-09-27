"""
Field types for starlette-cms block and document definitions.

Each field type wraps a Pydantic FieldInfo with additional schema metadata
that is passed through to /api/schema under the cms:field_meta key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Union

from pydantic import Field as PydanticField


@dataclass
class _BaseField:
    required: bool = False
    label: str | None = None
    placeholder: str | None = None
    help_text: str | None = None
    display_order: int | None = None
    group: str | None = None
    immutable: bool = False

    def field_meta(self) -> dict[str, Any]:
        meta = {
            k: v
            for k, v in {
                "label": self.label,
                "placeholder": self.placeholder,
                "help_text": self.help_text,
                "display_order": self.display_order,
                "group": self.group,
            }.items()
            if v is not None
        }
        if self.immutable:
            meta["immutable"] = True
        return meta

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        """
        Return ``(type, field_kwargs)`` describing this field's Pydantic
        representation — ``field_kwargs`` is a plain dict of keyword arguments
        for ``pydantic.Field(...)`` (e.g. ``{"default": None}`` or
        ``{"ge": 0, "le": 10}``), kept as plain data rather than a built
        ``FieldInfo`` so this module stays free of a hard pydantic.Field(...)
        construction dependency for the common case.

        Every ``_BaseField`` subclass should override this. The default here
        is the historical "unregistered type" fallback: use the raw
        annotation as-is. A new field type that forgets to override this
        degrades to that fallback instead of erroring — model_builder never
        needs to know this class exists.
        """
        fallback_type: Any = annotation if annotation is not None else Any
        if optional:
            return (fallback_type | None, {"default": None})
        return (fallback_type, {"default": ...})


@dataclass
class TextField(_BaseField):
    """Short text input — the most common field type.

    Examples::

        title: str = TextField(required=True, label="Title", max_length=200)
        slug: str = TextField(required=True, unique_per_type=True)
    """

    max_length: int | None = None
    unique_per_type: bool = False

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (str | None, {"default": None})
        return (str, {"default": ...})


@dataclass
class RichTextField(_BaseField):
    """Stores ProseMirror document JSON."""

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "rich_text"
        return m

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (dict | None, {"default": None})
        return (dict, {"default": ...})


@dataclass
class ImageField(_BaseField):
    """Stores a media reference — URL string or Mediakit asset key."""

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "image"
        return m

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (str | None, {"default": None})
        return (str, {"default": ...})


@dataclass
class ListField(_BaseField):
    """
    A list of items. Pass a single block class for a homogeneous list,
    or a list of block classes for a polymorphic block list.

    Examples::

        cards: list = ListField(CardBlock)
        body: list = ListField(blocks=[HeroBlock, CardSectionBlock])
    """

    item_type: Any = None
    blocks: list[Any] = field(default_factory=list)

    def __init__(self, item_type: Any = None, *, blocks: list[Any] | None = None, **kwargs: Any):
        super().__init__(**kwargs)
        if blocks is not None:
            self.blocks = blocks
            self.item_type = None
        else:
            self.item_type = item_type
            self.blocks = []

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "block_list"
        return m

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if self.blocks:
            # Polymorphic block list — discriminated union
            union_type: Any = Union[tuple(self.blocks)]  # noqa: UP007
            item_ann = Annotated[union_type, PydanticField(discriminator="block_type")]
            list_type: Any = list[item_ann]
        elif self.item_type is not None:
            list_type = list[self.item_type]
        else:
            list_type = list[Any]

        if optional:
            return (list_type | None, {"default": None})
        return (list_type, {"default_factory": list})


@dataclass
class BlockField(_BaseField):
    """A single nested block."""

    block_type: Any = None

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "block"
        return m

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        block_cls = self.block_type
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
            return (block_cls | None, {"default": None})
        return (block_cls, {"default": ...})


@dataclass
class NumberField(_BaseField):
    """Numeric field — stored as float.

    Examples::

        price: float = NumberField(required=True, min_value=0.0, label="Price")
        score: float = NumberField(min_value=0.0, max_value=100.0, precision=2)
    """

    min_value: float | None = None
    max_value: float | None = None
    precision: int | None = None
    default: float | int | None = None

    def field_meta(self) -> dict[str, Any]:
        base = super().field_meta()
        extras = {
            "min_value": self.min_value,
            "max_value": self.max_value,
            "precision": self.precision,
        }
        return {**base, **{k: v for k, v in extras.items() if v is not None}}

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        if self.min_value is not None:
            kwargs["ge"] = self.min_value
        if self.max_value is not None:
            kwargs["le"] = self.max_value
        if self.default is not None:
            kwargs["default"] = self.default
        else:
            kwargs["default"] = None if optional else ...
        float_type: Any = float | None if optional else float
        return (float_type, kwargs)


@dataclass
class SelectField(_BaseField):
    """Single-select (or future multi-select) from a fixed list of choices.

    Examples::

        status: str = SelectField(choices=["draft", "published"], required=True)
        tier: str = SelectField(choices=["bronze", "silver", "gold"])
    """

    choices: list[str] = field(default_factory=list)
    multiple: bool = False

    def field_meta(self) -> dict[str, Any]:
        base = super().field_meta()
        extras: dict[str, Any] = {"choices": self.choices}
        if self.multiple:
            extras["multiple"] = self.multiple
        return {**base, **extras}

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        import warnings
        from typing import Literal

        if self.choices:
            lit_type: Any = Literal[tuple(self.choices)]
        else:
            # stacklevel=5: to_pydantic() <- _make_field() <- _collect_field_defs()
            # <- build_block_model()/build_document_model() <- caller's class def.
            # One deeper than the pre-refactor call site (_make_field warned directly).
            warnings.warn(
                "SelectField has no choices — falling back to str",
                stacklevel=5,
            )
            lit_type = str
        if optional:
            return (lit_type | None, {"default": None})
        return (lit_type, {"default": ...})


@dataclass
class BoolField(_BaseField):
    """Boolean field — always has a default (never None).

    Examples::

        active: bool = BoolField(default=True, label="Active")
        featured: bool = BoolField()
    """

    default: bool = False

    def field_meta(self) -> dict[str, Any]:
        base = super().field_meta()
        return {**base, "default": self.default}

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        return (bool, {"default": self.default})


@dataclass
class URLField(_BaseField):
    """URL string field. Stored as raw str in v1 — no URL validation enforced.

    Examples::

        website: str = URLField(required=True, label="Website URL")
        thumbnail: str = URLField(max_length=512)
    """

    max_length: int = 2048

    def field_meta(self) -> dict[str, Any]:
        base = super().field_meta()
        return {**base, "max_length": self.max_length, "format": "url"}

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (str | None, {"default": None})
        return (str, {"default": ...})


@dataclass
class JSONField(_BaseField):
    """Arbitrary JSON blob (dict or list). Always nullable — defaults to None.

    Pass an optional ``schema`` for editor tooling hints (not enforced in v1).

    Examples::

        metadata: dict | list | None = JSONField()
        config: dict | list | None = JSONField(schema={"type": "object"})
    """

    schema: dict | None = None

    def field_meta(self) -> dict[str, Any]:
        base = super().field_meta()
        if self.schema is not None:
            return {**base, "schema": self.schema}
        return base

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if not optional:
            return (dict | list, {"default": ...})
        return (dict | list | None, {"default": None})


@dataclass
class DocumentRef(_BaseField):
    """
    A typed foreign key to another document.

    Stores the target document's ID string. Validates on write that the
    referenced document exists and has the declared block_type.

    ``on_delete`` controls behaviour when the referenced document is deleted:
    - ``"block"``   — refuse to delete the target (default)
    - ``"nullify"`` — set this field to None in all referencing documents
    - ``"cascade"`` — delete all documents referencing the target (dangerous)

    Example::

        submission_ref: str = DocumentRef(block_type="jewelry_item", immutable=True)
    """

    block_type: str | None = None
    on_delete: str = "block"

    def field_meta(self) -> dict[str, Any]:
        meta = super().field_meta()
        if self.block_type:
            meta["ref_block_type"] = self.block_type
        meta["on_delete"] = self.on_delete
        meta["field_type"] = "document_ref"
        return meta

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (str | None, {"default": None})
        return (str, {"default": ...})


@dataclass
class DoodleField(_BaseField):
    """
    A list of freehand SVG doodles, each with a responsive placement spec.

    Stored as a plain JSON array in the document body — same shape as
    ``ListField(item_type=...)`` without the polymorphism, tagged with its
    own field_type so the editor mounts a draw/place widget instead of the
    generic block canvas. A document can have zero, one, or many doodles.

    Example::

        doodles: list = DoodleField(label="Doodles")
    """

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "doodles"
        return m

    def to_pydantic(self, annotation: Any, optional: bool) -> tuple[Any, dict[str, Any]]:
        if optional:
            return (list[dict] | None, {"default": None})
        return (list[dict], {"default_factory": list})
