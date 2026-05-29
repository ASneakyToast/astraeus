"""Tests for CMS authentication modes."""

from __future__ import annotations

import os
import tempfile

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField

# ---------------------------------------------------------------------------
# Fixtures — auth modes
# ---------------------------------------------------------------------------


def _build_cms(auth, api_key=None, read_auth=False) -> tuple[CMS, str]:
    """Return (cms, db_path)."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db_path = f.name

    instance = CMS(
        database_url=f"sqlite:///{db_path}",
        auth=auth,
        api_key=api_key,
        read_auth=read_auth,
    )

    @instance.block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    @instance.document("page")
    class PageDocument:
        title: str = TextField(required=True)
        slug: str = TextField(required=True)

    return instance, db_path


@pytest_asyncio.fixture
async def no_auth_client():
    cms, db_path = _build_cms(auth="none")
    app = Starlette(routes=[Mount("/", app=cms.app)])
    try:
        async with cms.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                yield client
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def apikey_client():
    cms, db_path = _build_cms(auth="apikey", api_key="secret123")
    app = Starlette(routes=[Mount("/", app=cms.app)])
    try:
        async with cms.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                yield cms, client
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def read_auth_client():
    """CMS with read_auth=True — even GETs require auth."""
    cms, db_path = _build_cms(auth="apikey", api_key="secret123", read_auth=True)
    app = Starlette(routes=[Mount("/", app=cms.app)])
    try:
        async with cms.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                yield cms, client
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# "none" mode — all requests allowed
# ---------------------------------------------------------------------------


async def test_none_auth_allows_get(no_auth_client):
    resp = await no_auth_client.get("/api/documents")
    assert resp.status_code == 200


async def test_none_auth_allows_post(no_auth_client):
    resp = await no_auth_client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
    )
    assert resp.status_code == 201


async def test_none_auth_allows_delete(no_auth_client):
    create = await no_auth_client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
    )
    doc_id = create.json()["id"]
    resp = await no_auth_client.delete(f"/api/documents/{doc_id}")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# "apikey" mode
# ---------------------------------------------------------------------------


async def test_apikey_blocks_post_without_header(apikey_client):
    _, client = apikey_client
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
    )
    assert resp.status_code == 401


async def test_apikey_blocks_patch_without_header(apikey_client):
    _, client = apikey_client
    resp = await client.patch("/api/documents/some-id", json={"body": {}})
    assert resp.status_code == 401


async def test_apikey_blocks_delete_without_header(apikey_client):
    _, client = apikey_client
    resp = await client.delete("/api/documents/some-id")
    assert resp.status_code == 401


async def test_apikey_allows_get_without_header(apikey_client):
    """GETs are public when read_auth=False (default)."""
    _, client = apikey_client
    resp = await client.get("/api/documents")
    assert resp.status_code == 200


async def test_apikey_allows_post_with_correct_header(apikey_client):
    _, client = apikey_client
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 201


async def test_apikey_blocks_wrong_key(apikey_client):
    _, client = apikey_client
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
        headers={"Authorization": "Bearer wrongkey"},
    )
    assert resp.status_code == 401


async def test_apikey_blocks_malformed_header(apikey_client):
    _, client = apikey_client
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"title": "T", "slug": "t"}, "slug": "t"},
        headers={"Authorization": "secret123"},  # missing "Bearer " prefix
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# read_auth=True — GETs also protected
# ---------------------------------------------------------------------------


async def test_read_auth_blocks_get_without_header(read_auth_client):
    _, client = read_auth_client
    resp = await client.get("/api/documents")
    assert resp.status_code == 401


async def test_read_auth_allows_get_with_header(read_auth_client):
    _, client = read_auth_client
    resp = await client.get(
        "/api/documents",
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 200


async def test_read_auth_blocks_schema_without_header(read_auth_client):
    _, client = read_auth_client
    resp = await client.get("/api/schema")
    assert resp.status_code == 401
