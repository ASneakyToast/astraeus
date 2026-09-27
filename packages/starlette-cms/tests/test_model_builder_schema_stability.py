"""
Regression check for the field-type polymorphism refactor (`to_pydantic()`
methods replacing `_make_field()`'s isinstance chain).

`fixtures/full_coverage_schema.json` was captured from the pre-refactor
isinstance-chain behavior and must never be regenerated silently — a failure
here means the refactor changed observable schema output for some field type.
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette_cms.fields import (
    BlockField,
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

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "full_coverage_schema.json"


class _HeroBlock:
    heading: str = TextField(required=True, label="Heading")


_HeroModel = build_block_model("hero", _HeroBlock)


class _FullCoverageDoc:
    """Exercises every field type in fields.py, required and optional branches
    where those differ, so a full JSON-schema diff catches any behavior change."""

    text_required: str = TextField(required=True, max_length=200)
    text_optional: str = TextField()
    rich_required: dict = RichTextField(required=True)
    rich_optional: dict = RichTextField()
    image_required: str = ImageField(required=True)
    image_optional: str = ImageField()
    list_homogeneous: list = ListField(item_type=_HeroModel)
    list_polymorphic: list = ListField(blocks=[_HeroModel])
    list_untyped: list = ListField()
    block_typed: dict = BlockField(block_type=_HeroModel)
    block_untyped: dict = BlockField()
    number_required: float = NumberField(required=True, min_value=0, max_value=10, precision=2)
    number_optional: float = NumberField(default=5.0)
    select_required: str = SelectField(required=True, choices=["a", "b"])
    boolean: bool = BoolField(default=True)
    url_field: str = URLField()
    json_required: dict = JSONField(required=True)
    json_optional: dict = JSONField(schema={"type": "object"})
    doc_ref_required: str = DocumentRef(required=True, block_type="post")
    doc_ref_optional: str = DocumentRef(block_type="post", on_delete="nullify")


def test_schema_output_unchanged_by_refactor():
    model = build_document_model("full_coverage", _FullCoverageDoc)
    actual = model.model_json_schema()
    expected = json.loads(FIXTURE_PATH.read_text())
    assert actual == expected
