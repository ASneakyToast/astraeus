"""Tests for Pydantic model generation — build_block_model and build_document_model."""

from __future__ import annotations

import pydantic
import pytest
from starlette_cms import (
    CMS,
    BoolField,
    DocumentRef,
    ImageField,
    JSONField,
    ListField,
    NumberField,
    RichTextField,
    SelectField,
    TextField,
    URLField,
)
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


# ---------------------------------------------------------------------------
# NumberField
# ---------------------------------------------------------------------------


def test_number_field_required():
    """Required NumberField accepts float, rejects non-numeric string."""

    class B:
        price: float = NumberField(required=True)

    model = build_block_model("b", B)
    instance = model(price=9.99)
    assert instance.price == 9.99  # type: ignore[attr-defined]

    with pytest.raises(pydantic.ValidationError):
        model(price="not-a-number")


def test_number_field_optional_defaults_none():
    """Optional NumberField defaults to None when omitted."""

    class B:
        score: float = NumberField(required=False)

    model = build_block_model("b", B)
    instance = model()
    assert instance.score is None  # type: ignore[attr-defined]


def test_number_field_min_max():
    """Value below min_value raises ValidationError."""

    class B:
        pct: float = NumberField(required=True, min_value=0.0, max_value=100.0)

    model = build_block_model("b", B)
    with pytest.raises(pydantic.ValidationError):
        model(pct=-1.0)

    with pytest.raises(pydantic.ValidationError):
        model(pct=101.0)

    instance = model(pct=50.0)
    assert instance.pct == 50.0  # type: ignore[attr-defined]


def test_number_field_with_default():
    """NumberField.default flows through to Pydantic — field can be omitted."""

    class B:
        rate: float = NumberField(default=1.5)

    model = build_block_model("b", B)
    instance = model()
    assert instance.rate == 1.5  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# SelectField
# ---------------------------------------------------------------------------


def test_select_field_required():
    """Required SelectField rejects values outside choices."""

    class B:
        status: str = SelectField(choices=["draft", "published"], required=True)

    model = build_block_model("b", B)
    instance = model(status="draft")
    assert instance.status == "draft"  # type: ignore[attr-defined]

    with pytest.raises(pydantic.ValidationError):
        model(status="archived")


def test_select_field_optional():
    """Optional SelectField accepts None."""

    class B:
        tier: str = SelectField(choices=["bronze", "silver", "gold"], required=False)

    model = build_block_model("b", B)
    instance = model()
    assert instance.tier is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# BoolField
# ---------------------------------------------------------------------------


def test_bool_field_default_false():
    """BoolField defaults to False when not provided."""

    class B:
        active: bool = BoolField()

    model = build_block_model("b", B)
    instance = model()
    assert instance.active is False  # type: ignore[attr-defined]


def test_bool_field_explicit_true():
    """BoolField accepts explicit True."""

    class B:
        featured: bool = BoolField(default=False)

    model = build_block_model("b", B)
    instance = model(featured=True)
    assert instance.featured is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# URLField
# ---------------------------------------------------------------------------


def test_url_field_required():
    """Required URLField accepts any string in v1 (no URL format enforcement)."""

    class B:
        website: str = URLField(required=True)

    model = build_block_model("b", B)
    instance = model(website="https://example.com")
    assert instance.website == "https://example.com"  # type: ignore[attr-defined]

    with pytest.raises(pydantic.ValidationError):
        model()  # missing required field


# ---------------------------------------------------------------------------
# JSONField
# ---------------------------------------------------------------------------


def test_json_field_accepts_dict():
    """JSONField validates a plain dict."""

    class B:
        metadata: dict = JSONField()

    model = build_block_model("b", B)
    instance = model(metadata={"key": "value"})
    assert instance.metadata == {"key": "value"}  # type: ignore[attr-defined]


def test_json_field_accepts_list():
    """JSONField validates a list."""

    class B:
        items: list = JSONField()

    model = build_block_model("b", B)
    instance = model(items=[1, 2, 3])
    assert instance.items == [1, 2, 3]  # type: ignore[attr-defined]


def test_json_field_optional_defaults_none():
    """JSONField defaults to None when not provided."""

    class B:
        config: dict = JSONField()

    model = build_block_model("b", B)
    instance = model()
    assert instance.config is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# DocumentRef field type
# ---------------------------------------------------------------------------


def test_documentref_field_type_is_str():
    """A DocumentRef generates a str | None Pydantic field (optional by default)."""

    class B:
        submission_ref: str = DocumentRef(block_type="jewelry_item")

    model = build_block_model("b", B)
    instance = model()
    assert instance.submission_ref is None  # type: ignore[attr-defined]


def test_documentref_required_field_type_is_str():
    """A required DocumentRef generates a str Pydantic field."""

    class B:
        submission_ref: str = DocumentRef(block_type="jewelry_item", required=True)

    model = build_block_model("b", B)
    with pytest.raises(pydantic.ValidationError):
        model()  # required — must be provided
    instance = model(submission_ref="doc-abc")
    assert instance.submission_ref == "doc-abc"  # type: ignore[attr-defined]


def test_documentref_optional_defaults_none():
    """Optional DocumentRef defaults to None."""

    class B:
        rule_config_ref: str = DocumentRef(block_type="global_thresholds")

    model = build_document_model("b", B)
    instance = model()
    assert instance.rule_config_ref is None  # type: ignore[attr-defined]


def test_documentref_ref_fields_dict_on_model():
    """build_block_model populates __ref_fields__ mapping field name to DocumentRef descriptor."""

    class B:
        submission_ref: str = DocumentRef(block_type="jewelry_item")
        score: str = TextField()

    model = build_block_model("b", B)
    assert hasattr(model, "__ref_fields__")
    ref_fields = model.__ref_fields__  # type: ignore[attr-defined]
    assert "submission_ref" in ref_fields
    assert ref_fields["submission_ref"].block_type == "jewelry_item"
    assert "score" not in ref_fields


def test_documentref_field_meta_includes_ref_block_type():
    """DocumentRef.field_meta() includes ref_block_type."""

    ref = DocumentRef(block_type="jewelry_item", label="Submission")
    meta = ref.field_meta()
    assert meta["ref_block_type"] == "jewelry_item"
    assert meta["field_type"] == "document_ref"
    assert meta["on_delete"] == "block"
    assert meta["label"] == "Submission"


def test_documentref_field_meta_on_delete_nullify():
    """DocumentRef with on_delete='nullify' reflects that in field_meta."""

    ref = DocumentRef(block_type="global_thresholds", on_delete="nullify")
    meta = ref.field_meta()
    assert meta["on_delete"] == "nullify"


# ---------------------------------------------------------------------------
# __immutable_fields__ collection
# ---------------------------------------------------------------------------


def test_immutable_fields_collected():
    """build_block_model sets __immutable_fields__ with correct names."""

    class EvalBlock:
        ref: str = TextField(required=True, immutable=True)
        score: str = TextField(required=True)

    model = build_block_model("eval", EvalBlock)
    assert hasattr(model, "__immutable_fields__")
    assert "ref" in model.__immutable_fields__  # type: ignore[attr-defined]


def test_non_immutable_not_in_set():
    """Mutable fields are not in __immutable_fields__."""

    class EvalBlock:
        ref: str = TextField(required=True, immutable=True)
        score: str = TextField(required=True)

    model = build_block_model("eval", EvalBlock)
    assert "score" not in model.__immutable_fields__  # type: ignore[attr-defined]
