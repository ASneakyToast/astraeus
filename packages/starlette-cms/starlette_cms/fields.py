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

    def field_meta(self) -> dict[str, Any]:
        return {k: v for k, v in {
            "label": self.label,
            "placeholder": self.placeholder,
            "help_text": self.help_text,
            "display_order": self.display_order,
            "group": self.group,
        }.items() if v is not None}


@dataclass
class TextField(_BaseField):
    max_length: int | None = None
    unique_per_type: bool = False


@dataclass
class RichTextField(_BaseField):
    """Stores ProseMirror document JSON."""
    pass


@dataclass
class ImageField(_BaseField):
    """Stores a media reference — URL string or Mediakit asset key."""
    pass


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
