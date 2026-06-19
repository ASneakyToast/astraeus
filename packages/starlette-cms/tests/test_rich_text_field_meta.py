"""
Tests for field_type metadata on RichTextField, ImageField, and TextField.
"""

from __future__ import annotations

from starlette_cms.fields import ImageField, RichTextField, TextField


def test_rich_text_field_meta_has_field_type():
    meta = RichTextField().field_meta()
    assert meta["field_type"] == "rich_text"


def test_image_field_meta_has_field_type():
    meta = ImageField().field_meta()
    assert meta["field_type"] == "image"


def test_text_field_meta_has_no_field_type():
    meta = TextField().field_meta()
    assert "field_type" not in meta
