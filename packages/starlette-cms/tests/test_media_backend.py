"""
Tests for MediaBackend protocol + ImageField validation.

Verifies that:
- Without a backend, any ImageField value is accepted
- With a backend that returns True, saves succeed
- With a backend that returns False, saves return 422 with the field name
"""

from __future__ import annotations

import os
import tempfile

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, ImageField, MediaBackend, TextField

# ---------------------------------------------------------------------------
# Minimal MediaBackend implementations
# ---------------------------------------------------------------------------


class AlwaysExists:
    """MediaBackend stub that always confirms the key exists."""

    async def confirm_exists(self, key: str) -> bool:
        return True


class NeverExists:
    """MediaBackend stub that always says the key does not exist."""

    async def confirm_exists(self, key: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cms_no_backend():
    """CMS with an ImageField document but no media backend."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
        )

        @instance.document("post")
        class PostDocument:
            title: str = TextField(required=True)
            cover: str = ImageField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def cms_always_exists():
    """CMS with AlwaysExists media backend."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            media_backend=AlwaysExists(),
        )

        @instance.document("post")
        class PostDocument:
            title: str = TextField(required=True)
            cover: str = ImageField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def cms_never_exists():
    """CMS with NeverExists media backend."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            media_backend=NeverExists(),
        )

        @instance.document("post")
        class PostDocument:
            title: str = TextField(required=True)
            cover: str = ImageField(required=False)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _make_client(cms: CMS) -> httpx.AsyncClient:
    app = Starlette(routes=[Mount("/", app=cms.app)])
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_always_exists_implements_protocol():
    """AlwaysExists satisfies the MediaBackend runtime-checkable protocol."""
    assert isinstance(AlwaysExists(), MediaBackend)


def test_never_exists_implements_protocol():
    """NeverExists satisfies the MediaBackend runtime-checkable protocol."""
    assert isinstance(NeverExists(), MediaBackend)


# ---------------------------------------------------------------------------
# No backend — all ImageField values accepted
# ---------------------------------------------------------------------------


async def test_no_backend_image_accepted(cms_no_backend):
    """Without a backend, ImageField values are accepted without validation."""
    async with _make_client(cms_no_backend) as client:
        resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "post",
                "slug": "no-backend",
                "body": {"title": "Hello", "cover": "originals/abc123/image.jpg"},
            },
        )
    assert resp.status_code == 201
    assert resp.json()["body"]["cover"] == "originals/abc123/image.jpg"


async def test_no_backend_none_image_accepted(cms_no_backend):
    """Without a backend, a None/absent ImageField is accepted."""
    async with _make_client(cms_no_backend) as client:
        resp = await client.post(
            "/api/documents",
            json={"doc_type": "post", "slug": "no-cover", "body": {"title": "No cover"}},
        )
    assert resp.status_code == 201


# ---------------------------------------------------------------------------
# AlwaysExists backend — saves succeed
# ---------------------------------------------------------------------------


async def test_backend_confirms_exists_create(cms_always_exists):
    """With AlwaysExists backend, create with ImageField value succeeds."""
    async with _make_client(cms_always_exists) as client:
        resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "post",
                "slug": "with-cover",
                "body": {"title": "With cover", "cover": "originals/abc/img.jpg"},
            },
        )
    assert resp.status_code == 201


async def test_backend_confirms_exists_patch(cms_always_exists):
    """With AlwaysExists backend, patch with ImageField value succeeds."""
    async with _make_client(cms_always_exists) as client:
        create_resp = await client.post(
            "/api/documents",
            json={"doc_type": "post", "slug": "cover-patch", "body": {"title": "Before"}},
        )
        doc_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"cover": "originals/xyz/new.jpg"}},
        )
    assert patch_resp.status_code == 200


# ---------------------------------------------------------------------------
# NeverExists backend — ImageField values rejected with 422
# ---------------------------------------------------------------------------


async def test_backend_missing_image_create(cms_never_exists):
    """With NeverExists backend, create with ImageField value returns 422."""
    async with _make_client(cms_never_exists) as client:
        resp = await client.post(
            "/api/documents",
            json={
                "doc_type": "post",
                "slug": "bad-cover",
                "body": {"title": "Bad cover", "cover": "originals/missing/image.jpg"},
            },
        )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "Image key not found"
    assert body["field"] == "cover"


async def test_backend_missing_image_patch(cms_never_exists):
    """With NeverExists backend, patch with ImageField value returns 422."""
    async with _make_client(cms_never_exists) as client:
        # Create first without a cover value (NeverExists only blocks non-None values)
        create_resp = await client.post(
            "/api/documents",
            json={"doc_type": "post", "slug": "patch-bad", "body": {"title": "Patch bad"}},
        )
        doc_id = create_resp.json()["id"]

        patch_resp = await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"cover": "originals/missing/new.jpg"}},
        )

    assert patch_resp.status_code == 422
    body = patch_resp.json()
    assert body["error"] == "Image key not found"
    assert body["field"] == "cover"


async def test_backend_none_image_skipped(cms_never_exists):
    """NeverExists backend: None/absent cover skips validation entirely."""
    async with _make_client(cms_never_exists) as client:
        resp = await client.post(
            "/api/documents",
            json={"doc_type": "post", "slug": "null-cover", "body": {"title": "Null cover"}},
        )
    # cover is None/absent — NeverExists is never called, save succeeds
    assert resp.status_code == 201
