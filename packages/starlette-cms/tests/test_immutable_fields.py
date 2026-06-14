"""
Tests for immutable=True field property (ADR 013).

Verifies that:
- immutable fields are accessible in __immutable_fields__ on the document model
- immutable=True is surfaced in the schema API under cms:field_meta
- PATCH requests silently drop immutable fields (the original value is preserved)
- Non-immutable fields on the same document are still writable
- CREATE accepts immutable fields normally (immutability only prevents post-creation changes)
- Documents with no immutable fields are unaffected
"""

from __future__ import annotations

import os
import tempfile

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField
from starlette_cms.fields import _BaseField

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(cms: CMS) -> httpx.AsyncClient:
    app = Starlette(routes=[Mount("/", app=cms.app)])
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )


# ---------------------------------------------------------------------------
# Fixture — CMS with a document that has a mix of immutable and mutable fields
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cms_with_immutable():
    """
    CMS with an 'eval_entry' document type that mimics the EvalEntry pattern:
    - submission_ref: immutable — set at create, must not change on PATCH
    - score: mutable — reviewer can update
    - notes: mutable — reviewer can update
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.document("eval_entry")
        class EvalEntry:
            submission_ref: str = TextField(required=True, immutable=True)
            score: str = TextField(required=True)
            notes: str = TextField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def cms_no_immutable():
    """CMS with a plain document — no immutable fields."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.document("page")
        class PageDocument:
            title: str = TextField(required=True)
            body: str = TextField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Field property tests
# ---------------------------------------------------------------------------


def test_immutable_flag_on_field():
    """`immutable=True` is stored on the field instance."""
    field = TextField(required=True, immutable=True)
    assert field.immutable is True


def test_immutable_defaults_false():
    """`immutable` defaults to False — no change to existing field definitions."""
    field = TextField(required=True)
    assert field.immutable is False


def test_immutable_in_field_meta():
    """`immutable=True` is surfaced in field_meta() for schema introspection."""
    field = TextField(required=True, immutable=True)
    assert field.field_meta().get("immutable") is True


def test_immutable_absent_from_field_meta_when_false():
    """`immutable` key is absent from field_meta() when False — keeps schema clean."""
    field = TextField(required=True)
    assert "immutable" not in field.field_meta()


def test_immutable_fields_on_document_model(cms_with_immutable):
    """__immutable_fields__ on the document model lists only immutable fields."""
    model = cms_with_immutable._document_types["eval_entry"]
    assert hasattr(model, "__immutable_fields__")
    assert model.__immutable_fields__ == ["submission_ref"]


def test_no_immutable_fields_on_plain_model(cms_no_immutable):
    """__immutable_fields__ is empty for documents with no immutable fields."""
    model = cms_no_immutable._document_types["page"]
    assert model.__immutable_fields__ == []


def test_immutable_is_a_base_field_property():
    """`immutable` is defined on _BaseField, so all field subclasses inherit it."""
    import dataclasses

    field_names = [f.name for f in dataclasses.fields(_BaseField)]
    assert "immutable" in field_names


# ---------------------------------------------------------------------------
# Schema API — immutable surfaced in cms:field_meta
#
# The schema endpoint serves block types (cms.registry), not document types.
# We use a CMS with a registered block that has an immutable field.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cms_with_immutable_block():
    """CMS with a registered block containing an immutable field."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.block("evidence_block")
        class EvidenceBlock:
            ref: str = TextField(required=True, immutable=True)
            label: str = TextField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def test_schema_includes_immutable_flag(cms_with_immutable_block):
    """GET /api/schema/{block_type} surfaces immutable=true in cms:field_meta."""
    async with _make_client(cms_with_immutable_block) as client:
        resp = await client.get("/api/schema/evidence_block")

    assert resp.status_code == 200
    schema = resp.json()
    props = schema.get("schema", {}).get("properties", {})
    ref_meta = props.get("ref", {}).get("cms:field_meta", {})
    assert ref_meta.get("immutable") is True


async def test_schema_mutable_field_no_immutable_flag(cms_with_immutable_block):
    """Mutable fields do not have immutable in their cms:field_meta."""
    async with _make_client(cms_with_immutable_block) as client:
        resp = await client.get("/api/schema/evidence_block")

    assert resp.status_code == 200
    schema = resp.json()
    props = schema.get("schema", {}).get("properties", {})
    label_meta = props.get("label", {}).get("cms:field_meta", {})
    assert "immutable" not in label_meta


# ---------------------------------------------------------------------------
# CREATE — immutable fields accepted normally
# ---------------------------------------------------------------------------


async def test_create_accepts_immutable_field(cms_with_immutable):
    """CREATE accepts immutable fields — immutability only restricts PATCH."""
    async with _make_client(cms_with_immutable) as client:
        resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "eval_entry",
                "slug": "entry-1",
                "body": {
                    "submission_ref": "doc_abc123",
                    "score": "5",
                    "notes": "Great result",
                },
            },
        )

    assert resp.status_code == 201
    body = resp.json()["body"]
    assert body["submission_ref"] == "doc_abc123"
    assert body["score"] == "5"


# ---------------------------------------------------------------------------
# PATCH — immutable fields silently stripped, mutable fields still writable
# ---------------------------------------------------------------------------


async def test_patch_immutable_field_is_silently_ignored(cms_with_immutable):
    """PATCH including an immutable field returns 200 but the field is unchanged."""
    async with _make_client(cms_with_immutable) as client:
        # Create the document
        create_resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "eval_entry",
                "slug": "entry-immutable",
                "body": {
                    "submission_ref": "doc_original",
                    "score": "3",
                },
            },
        )
        assert create_resp.status_code == 201
        doc_id = create_resp.json()["id"]

        # PATCH attempting to change the immutable field
        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"submission_ref": "doc_CHANGED", "score": "5"}},
        )

    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    # submission_ref unchanged — immutable field was stripped
    assert body["submission_ref"] == "doc_original"
    # score updated — mutable field written normally
    assert body["score"] == "5"


async def test_patch_only_immutable_field_is_no_op(cms_with_immutable):
    """PATCH with only immutable fields results in no body changes."""
    async with _make_client(cms_with_immutable) as client:
        create_resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "eval_entry",
                "slug": "entry-noop",
                "body": {"submission_ref": "doc_abc", "score": "4"},
            },
        )
        doc_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"submission_ref": "doc_DIFFERENT"}},
        )

    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["submission_ref"] == "doc_abc"
    assert body["score"] == "4"


async def test_patch_mutable_field_updates_normally(cms_with_immutable):
    """Mutable fields on a document with immutable fields still update correctly."""
    async with _make_client(cms_with_immutable) as client:
        create_resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "eval_entry",
                "slug": "entry-mutable",
                "body": {"submission_ref": "doc_xyz", "score": "2", "notes": "initial"},
            },
        )
        doc_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"score": "5", "notes": "revised after review"}},
        )

    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["submission_ref"] == "doc_xyz"  # untouched
    assert body["score"] == "5"
    assert body["notes"] == "revised after review"


# ---------------------------------------------------------------------------
# Documents without immutable fields are unaffected
# ---------------------------------------------------------------------------


async def test_plain_document_patch_unaffected(cms_no_immutable):
    """PATCH on a document with no immutable fields works as before."""
    async with _make_client(cms_no_immutable) as client:
        create_resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": "plain-page",
                "body": {"title": "Original", "body": "First draft"},
            },
        )
        doc_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"title": "Updated", "body": "Second draft"}},
        )

    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["title"] == "Updated"
    assert body["body"] == "Second draft"
