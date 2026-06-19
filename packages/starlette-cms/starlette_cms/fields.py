"""
Field types for starlette-cms block and document definitions.

Each field type wraps a Pydantic FieldInfo with additional schema metadata
that is passed through to /api/schema under the cms:field_meta key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class TextField(_BaseField):
    """Short text input — the most common field type.

    Examples::

        title: str = TextField(required=True, label="Title", max_length=200)
        slug: str = TextField(required=True, unique_per_type=True)
    """

    max_length: int | None = None
    unique_per_type: bool = False


@dataclass
class RichTextField(_BaseField):
    """Stores ProseMirror document JSON."""

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "rich_text"
        return m


@dataclass
class ImageField(_BaseField):
    """Stores a media reference — URL string or Mediakit asset key."""

    def field_meta(self) -> dict[str, Any]:
        m = super().field_meta()
        m["field_type"] = "image"
        return m


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


@dataclass
class BlockField(_BaseField):
    """A single nested block."""

    block_type: Any = None


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
