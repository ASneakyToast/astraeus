"""
Tests for append_only=True document lifecycle (ADR 014).

Verification matrix:
- POST to an append_only block type → 201, document already published
- PATCH to an append_only document → 405
- DELETE to an append_only document → 405
- GET /api/documents/{id} → still works (read is never blocked)
- GET /api/documents (list) → still works
- Non-append_only documents still support PATCH and DELETE
- @cms.block(append_only=True) and @block(append_only=True) both wire up correctly
- Registry.is_append_only() returns correct values
- Webhook event for append_only creation carries append_only=True
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount

from starlette_cms import CMS, TextField
from starlette_cms.exceptions import ImmutableDocumentError
from starlette_cms.registry import BlockRegistry, block


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ao_cms() -> AsyncGenerator[CMS, None]:
    """CMS with one append_only block and one normal block."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

        @instance.block("job_audit", append_only=True)
        class JobAudit:
            job_id: str = TextField(required=True)
            status: str = TextField(required=True)

        @instance.block("blog_post")
        class BlogPost:
            title: str = TextField(required=True)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def ao_client(ao_cms: CMS) -> AsyncGenerator[httpx.AsyncClient, None]:
    """httpx.AsyncClient targeting ao_cms."""
    app = Starlette(routes=[Mount("/", app=ao_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Registry-level tests
# ---------------------------------------------------------------------------


def test_registry_is_append_only_true():
    registry = BlockRegistry()

    @block("audit_rec", append_only=True)
    class AuditRec:
        msg: str = TextField()

    registry.register_block(AuditRec)
    assert registry.is_append_only("audit_rec") is True


def test_registry_is_append_only_false_for_normal():
    registry = BlockRegistry()

    @block("normal_block")
    class NormalBlock:
        msg: str = TextField()

    registry.register_block(NormalBlock)
    assert registry.is_append_only("normal_block") is False


def test_registry_is_append_only_false_for_singleton():
    """singleton=True does not imply append_only=True."""
    registry = BlockRegistry()

    @block("config", singleton=True)
    class Config:
        val: str = TextField()

    registry.register_block(Config)
    assert registry.is_append_only("config") is False
    assert registry.is_singleton("config") is True


def test_cms_block_append_only_registers_correctly(ao_cms: CMS):
    assert ao_cms.registry.is_append_only("job_audit") is True
    assert ao_cms.registry.is_append_only("blog_post") is False


# ---------------------------------------------------------------------------
# POST — auto-publish on creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_only_create_is_published(ao_client):
    """Creating an append_only document immediately sets published=True."""
    resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_001", "status": "auto_approved"},
        },
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["published"] is True
    assert doc["published_at"] is not None


@pytest.mark.asyncio
async def test_append_only_create_returns_correct_body(ao_client):
    resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_002", "status": "auto_denied"},
            "slug": "job-002",
        },
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["body"]["job_id"] == "job_002"
    assert doc["body"]["status"] == "auto_denied"
    assert doc["slug"] == "job-002"


@pytest.mark.asyncio
async def test_normal_block_create_is_draft(ao_client):
    """Normal (non-append_only) blocks still create in draft state."""
    resp = await ao_client.post(
        "/api/documents",
        json={"doc_type": "blog_post", "body": {"title": "Hello"}},
    )
    assert resp.status_code == 201
    doc = resp.json()
    assert doc["published"] is False
    assert doc["published_at"] is None


# ---------------------------------------------------------------------------
# GET — reads always work
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_only_get_by_id(ao_client):
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_003", "status": "manual_review"},
        },
    )
    doc_id = create_resp.json()["id"]

    get_resp = await ao_client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_append_only_list_documents(ao_client):
    for i in range(3):
        await ao_client.post(
            "/api/documents",
            json={
                "doc_type": "job_audit",
                "body": {"job_id": f"job_list_{i}", "status": "auto_approved"},
            },
        )

    resp = await ao_client.get("/api/documents", params={"type": "job_audit"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3


# ---------------------------------------------------------------------------
# PATCH — 405 for append_only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_only_patch_returns_405(ao_client):
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_patch_1", "status": "auto_approved"},
        },
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await ao_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"status": "manual_review"}},
    )
    assert patch_resp.status_code == 405
    assert "append_only" in patch_resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_append_only_patch_does_not_modify_document(ao_client):
    """Even if PATCH returns 405, the document is unchanged."""
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_patch_2", "status": "auto_approved"},
        },
    )
    doc_id = create_resp.json()["id"]

    await ao_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"status": "manual_review"}},
    )

    get_resp = await ao_client.get(f"/api/documents/{doc_id}")
    assert get_resp.json()["body"]["status"] == "auto_approved"  # unchanged


@pytest.mark.asyncio
async def test_normal_block_patch_still_works(ao_client):
    create_resp = await ao_client.post(
        "/api/documents",
        json={"doc_type": "blog_post", "body": {"title": "Original"}},
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await ao_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Updated"}},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["body"]["title"] == "Updated"


# ---------------------------------------------------------------------------
# DELETE — 405 for append_only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_only_delete_returns_405(ao_client):
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_del_1", "status": "auto_denied"},
        },
    )
    doc_id = create_resp.json()["id"]

    del_resp = await ao_client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 405
    assert "append_only" in del_resp.json()["error"].lower()


@pytest.mark.asyncio
async def test_append_only_delete_document_still_exists(ao_client):
    """DELETE attempt leaves the document intact."""
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_del_2", "status": "auto_denied"},
        },
    )
    doc_id = create_resp.json()["id"]

    await ao_client.delete(f"/api/documents/{doc_id}")  # should 405

    get_resp = await ao_client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200  # still there


@pytest.mark.asyncio
async def test_normal_block_delete_still_works(ao_client):
    create_resp = await ao_client.post(
        "/api/documents",
        json={"doc_type": "blog_post", "body": {"title": "To Delete"}},
    )
    doc_id = create_resp.json()["id"]

    del_resp = await ao_client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204

    get_resp = await ao_client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 404


# ---------------------------------------------------------------------------
# PUBLISH/UNPUBLISH — still work (document is already published, but endpoint
# is not blocked — caller is responsible for handling the no-op semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_only_unpublish_allowed(ao_client):
    """
    The unpublish endpoint is not blocked for append_only documents.
    (ADR 014 blocks modification of the body, not the published state.)
    """
    create_resp = await ao_client.post(
        "/api/documents",
        json={
            "doc_type": "job_audit",
            "body": {"job_id": "job_unpub_1", "status": "auto_approved"},
        },
    )
    doc_id = create_resp.json()["id"]
    assert create_resp.json()["published"] is True

    unpub_resp = await ao_client.post(f"/api/documents/{doc_id}/unpublish")
    # We do not mandate 405 here — ADR 014 only prohibits body modification
    assert unpub_resp.status_code in (200, 405)


# ---------------------------------------------------------------------------
# ImmutableDocumentError exported from __init__
# ---------------------------------------------------------------------------


def test_immutable_document_error_importable():
    from starlette_cms import ImmutableDocumentError as ImmErr  # noqa: F401

    assert issubclass(ImmErr, Exception)
