"""Tests for the /embed.js route."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytest_plugins = ["anyio"]


def _build_editor():
    """Build a (cms, editor) pair for testing."""
    from starlette_cms.app import CMS
    from starlette_editor.app import Editor

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    editor = Editor(cms=cms, mount_path="/editor")
    return cms, editor


@pytest.mark.anyio
async def test_embed_js_served():
    """GET /embed.js returns 200 with a JavaScript content type."""
    _, editor = _build_editor()
    async with AsyncClient(
        transport=ASGITransport(app=editor.app), base_url="http://test"
    ) as client:
        resp = await client.get("/embed.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_embed_js_cache_control():
    """GET /embed.js includes a 1-hour cache-control header."""
    _, editor = _build_editor()
    async with AsyncClient(
        transport=ASGITransport(app=editor.app), base_url="http://test"
    ) as client:
        resp = await client.get("/embed.js")
    assert resp.status_code == 200
    assert "max-age=3600" in resp.headers.get("cache-control", "")


@pytest.mark.anyio
async def test_embed_js_content_nonempty():
    """GET /embed.js returns a non-trivial JS bundle (≥ 10KB — PM is bundled)."""
    _, editor = _build_editor()
    async with AsyncClient(
        transport=ASGITransport(app=editor.app), base_url="http://test"
    ) as client:
        resp = await client.get("/embed.js")
    assert resp.status_code == 200
    # ProseMirror is bundled — expect at least 10KB
    assert len(resp.content) > 10_000, (
        f"embed.js is suspiciously small ({len(resp.content)} bytes) — "
        "did the build complete?"
    )


@pytest.mark.anyio
async def test_embed_js_no_auth_required():
    """GET /embed.js is public — no auth needed."""
    from starlette_editor.app import Editor
    from starlette_cms.app import CMS

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    # Add an auth guard to the editor shell — /embed.js should still be accessible
    editor = Editor(cms=cms, mount_path="/editor", auth=lambda req: False)
    async with AsyncClient(
        transport=ASGITransport(app=editor.app), base_url="http://test"
    ) as client:
        # Shell should be blocked
        shell_resp = await client.get("/shell")
        assert shell_resp.status_code == 401

        # But embed.js should be public
        embed_resp = await client.get("/embed.js")
        assert embed_resp.status_code == 200
