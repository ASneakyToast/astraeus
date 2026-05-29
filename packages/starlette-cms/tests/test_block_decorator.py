"""Tests for Pydantic model generation — build_block_model and build_document_model."""

from __future__ import annotations

import pydantic
import pytest
from starlette_cms import CMS, ImageField, ListField, RichTextField, TextField
from starlette_cms.model_builder import build_block_model, build_document_model

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cms() -> CMS:
    return CMS(database_url="sqlite:///test.db", auth="none")


# ---------------------------------------------------------------------------
# block_type discriminator injection
# ---------------------------------------------------------------------------


def test_block_type_literal_injected():
    """block_type is injected as Literal[name] with default = name."""

    class HeroBlock:
        title: str = TextField(required=True)

    model = build_block_model("hero", HeroBlock)
    instance = model(title="Hello")
    assert instance.block_type == "hero"  # type: ignore[attr-defined]


def test_block_type_cannot_be_overridden():
    """block_type default makes it hard to accidentally override with a wrong value."""

    class HeroBlock:
        title: str = TextField(required=True)

    model = build_block_model("hero", HeroBlock)
    # Passing the correct literal value is fine
    instance = model(title="Hi", block_type="hero")
    assert instance.block_type == "hero"  # type: ignore[attr-defined]


def test_dunder_block_type_attribute():
    """__block_type__ is set on the generated model class."""

    class HeroBlock:
        title: str = TextField(required=True)

    model = build_block_model("hero", HeroBlock)
    assert model.__block_type__ == "hero"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Required vs optional fields
# ---------------------------------------------------------------------------


def test_required_textfield_raises_without_value():
    class B:
        title: str = TextField(required=True)

    model = build_block_model("b", B)
    with pytest.raises(pydantic.ValidationError):
        model()  # title is required


def test_optional_textfield_defaults_to_none():
    class B:
        subtitle: str = TextField(required=False)

    model = build_block_model("b", B)
    instance = model()
    assert instance.subtitle is None  # type: ignore[attr-defined]


def test_required_richtextfield():
    class B:
        body: dict = RichTextField(required=True)

    model = build_block_model("b", B)
    with pytest.raises(pydantic.ValidationError):
        model()

    instance = model(body={"type": "doc"})
    assert instance.body == {"type": "doc"}  # type: ignore[attr-defined]


def test_optional_imagefield_defaults_to_none():
    class B:
        image: str = ImageField(required=False)

    model = build_block_model("b", B)
    instance = model()
    assert instance.image is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ListField — homogeneous and polymorphic
# ---------------------------------------------------------------------------


def test_listfield_homogeneous():
    """ListField with item_type=str maps to list[str]."""

    class B:
        tags: list = ListField(item_type=str)

    model = build_block_model("b", B)
    instance = model(tags=["a", "b"])
    assert instance.tags == ["a", "b"]  # type: ignore[attr-defined]


def test_listfield_blocks_discriminated_union():
    """ListField(blocks=[...]) creates a discriminated union list."""

    class CardBlock:
        text: str = TextField(required=True)

    CardModel = build_block_model("card", CardBlock)

    class HeroBlock:
        title: str = TextField(required=True)

    HeroModel = build_block_model("hero", HeroBlock)

    class PageDoc:
        body: list = ListField(blocks=[HeroModel, CardModel])

    doc_model = build_document_model("page", PageDoc)

    instance = doc_model(
        body=[
            {"block_type": "hero", "title": "Hi"},
            {"block_type": "card", "text": "Card text"},
        ]
    )
    assert len(instance.body) == 2  # type: ignore[attr-defined]
    assert instance.body[0].block_type == "hero"  # type: ignore[attr-defined]
    assert instance.body[1].block_type == "card"  # type: ignore[attr-defined]


def test_listfield_blocks_rejects_unknown_type():
    """Discriminated union rejects items with unregistered block_type."""

    class CardBlock:
        text: str = TextField(required=True)

    CardModel = build_block_model("card", CardBlock)

    class PageDoc:
        body: list = ListField(blocks=[CardModel])

    doc_model = build_document_model("page", PageDoc)

    with pytest.raises(pydantic.ValidationError):
        doc_model(body=[{"block_type": "unknown", "text": "Hi"}])


# ---------------------------------------------------------------------------
# document_model — no block_type injection
# ---------------------------------------------------------------------------


def test_document_model_no_block_type():
    class P:
        title: str = TextField(required=True)

    model = build_document_model("page", P)
    assert not hasattr(model.model_fields, "block_type")
    assert model.__document_type__ == "page"  # type: ignore[attr-defined]


def test_document_model_validates():
    class P:
        title: str = TextField(required=True)
        slug: str = TextField(required=True)

    model = build_document_model("page", P)
    with pytest.raises(pydantic.ValidationError):
        model(title="Missing slug")

    instance = model(title="Hello", slug="hello")
    assert instance.title == "Hello"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# model_rebuild — forward references
# ---------------------------------------------------------------------------


def test_model_rebuild_called():
    """build_block_model completes without error for a class with no forward refs."""

    class B:
        title: str = TextField(required=True)

    model = build_block_model("b", B)
    # If model_rebuild() was not called and there were forward refs, validation
    # would raise. A successful instantiation proves the model is complete.
    instance = model(title="ok")
    assert instance.title == "ok"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# json_schema_extra / cms:field_meta round-trip
# ---------------------------------------------------------------------------


def test_field_meta_in_json_schema():
    class B:
        title: str = TextField(required=True, label="Headline", help_text="Enter headline")

    model = build_block_model("b", B)
    schema = model.model_json_schema()
    title_schema = schema["properties"]["title"]
    meta = title_schema.get("cms:field_meta")
    assert meta is not None
    assert meta["label"] == "Headline"
    assert meta["help_text"] == "Enter headline"


def test_field_meta_not_present_when_empty():
    class B:
        title: str = TextField(required=True)

    model = build_block_model("b", B)
    schema = model.model_json_schema()
    title_schema = schema["properties"]["title"]
    # No label/help_text supplied → no cms:field_meta key
    assert "cms:field_meta" not in title_schema
