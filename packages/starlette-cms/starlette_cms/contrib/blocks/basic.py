"""
Starter block set — ready-to-use blocks for common content patterns.

Register all at once::

    from starlette_cms.contrib.blocks.basic import register
    register(cms)

Or selectively::

    from starlette_cms.contrib.blocks.basic import RichTextBlock, ImageBlock
    cms.register_blocks([RichTextBlock, ImageBlock])
"""

from starlette_cms.fields import RichTextField, TextField, ImageField
from starlette_cms.registry import block


@block("rich_text")
class RichTextBlock:
    body: dict = RichTextField(required=True, label="Content")


@block("image")
class ImageBlock:
    image: str = ImageField(required=True, label="Image")
    caption: str = TextField(label="Caption")
    alt: str = TextField(label="Alt text")


@block("quote")
class QuoteBlock:
    quote: dict = RichTextField(required=True, label="Quote")
    attribution: str = TextField(label="Attribution")


@block("heading")
class HeadingBlock:
    text: str = TextField(required=True, label="Heading text")
    level: str = TextField(label="Level (h1–h6)", placeholder="h2")


def register(cms, override: bool = False) -> None:
    """Register all basic blocks into the provided CMS instance."""
    cms.register_blocks(
        [RichTextBlock, ImageBlock, QuoteBlock, HeadingBlock],
        override=override,
    )


__all__ = [
    "RichTextBlock",
    "ImageBlock",
    "QuoteBlock",
    "HeadingBlock",
    "register",
]
