"""Tests for starlette_cms.contrib.blocks.basic using BlockTestCase."""

from __future__ import annotations

from starlette_cms.contrib.blocks.basic import HeadingBlock, ImageBlock, QuoteBlock, RichTextBlock
from starlette_cms.testing import BlockTestCase

# ---------------------------------------------------------------------------
# RichTextBlock
# ---------------------------------------------------------------------------


class TestRichTextBlock(BlockTestCase):
    block_cls = RichTextBlock
    valid_data = {"body": {"type": "doc", "content": []}}

    def test_valid_data(self):
        self.assert_valid(self.valid_data)

    def test_body_required(self):
        self.assert_field_required("body")
        self.assert_invalid({})

    def test_body_label(self):
        self.assert_field_label("body", "Content")

    def test_fields_present(self):
        self.assert_fields("body")

    def test_roundtrip(self):
        self.assert_roundtrip(self.valid_data)


# ---------------------------------------------------------------------------
# ImageBlock
# ---------------------------------------------------------------------------


class TestImageBlock(BlockTestCase):
    block_cls = ImageBlock
    valid_data = {
        "image": "https://example.com/photo.jpg",
        "caption": "A nice photo",
        "alt": "Descriptive alt text",
    }

    def test_valid_data(self):
        self.assert_valid(self.valid_data)

    def test_image_required(self):
        self.assert_field_required("image")
        self.assert_invalid({"caption": "no image"})

    def test_optional_fields(self):
        self.assert_field_optional("caption")
        self.assert_field_optional("alt")

    def test_image_label(self):
        self.assert_field_label("image", "Image")

    def test_caption_label(self):
        self.assert_field_label("caption", "Caption")

    def test_alt_label(self):
        self.assert_field_label("alt", "Alt text")

    def test_fields_present(self):
        self.assert_fields("image", "caption", "alt")

    def test_valid_image_only(self):
        # caption and alt are optional
        self.assert_valid({"image": "https://example.com/img.png"})

    def test_roundtrip(self):
        self.assert_roundtrip(self.valid_data)


# ---------------------------------------------------------------------------
# QuoteBlock
# ---------------------------------------------------------------------------


class TestQuoteBlock(BlockTestCase):
    block_cls = QuoteBlock
    valid_data = {
        "quote": {"type": "doc", "content": []},
        "attribution": "Famous Person",
    }

    def test_valid_data(self):
        self.assert_valid(self.valid_data)

    def test_quote_required(self):
        self.assert_field_required("quote")
        self.assert_invalid({"attribution": "no quote"})

    def test_attribution_optional(self):
        self.assert_field_optional("attribution")

    def test_quote_label(self):
        self.assert_field_label("quote", "Quote")

    def test_attribution_label(self):
        self.assert_field_label("attribution", "Attribution")

    def test_fields_present(self):
        self.assert_fields("quote", "attribution")

    def test_valid_without_attribution(self):
        self.assert_valid({"quote": {"type": "doc", "content": []}})

    def test_roundtrip(self):
        self.assert_roundtrip(self.valid_data)


# ---------------------------------------------------------------------------
# HeadingBlock
# ---------------------------------------------------------------------------


class TestHeadingBlock(BlockTestCase):
    block_cls = HeadingBlock
    valid_data = {"text": "My Heading", "level": "h2"}

    def test_valid_data(self):
        self.assert_valid(self.valid_data)

    def test_text_required(self):
        self.assert_field_required("text")
        self.assert_invalid({"level": "h2"})

    def test_level_optional(self):
        self.assert_field_optional("level")

    def test_text_label(self):
        self.assert_field_label("text", "Heading text")

    def test_level_label(self):
        self.assert_field_label("level", "Level (h1–h6)")

    def test_fields_present(self):
        self.assert_fields("text", "level")

    def test_valid_without_level(self):
        self.assert_valid({"text": "Just a heading"})

    def test_roundtrip(self):
        self.assert_roundtrip(self.valid_data)
