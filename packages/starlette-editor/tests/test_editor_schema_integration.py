"""
Integration tests for starlette-editor: schema endpoint, shell route, config injection.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount

pytest_plugins = ["anyio"]


def _build_cms_and_editor():
    """Return a (cms, editor) pair for use in tests."""
    from starlette_cms.app import CMS
    from starlette_cms.fields import RichTextField, TextField
    from starlette_editor.app import Editor

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)

    @cms.block("post")
    class Post:
        title: str = TextField(required=True, label="Title")
        body: dict = RichTextField(label="Body")

    editor = Editor(cms=cms, mount_path="/editor")
    return cms, editor


def test_editor_registers_extension_route():
    """Editor.__init__ must register /api/editor-schema on the CMS."""
    from starlette_cms.app import CMS
    from starlette_editor.app import Editor

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    Editor(cms=cms, mount_path="/editor")

    # Extension routes are stored as dicts on cms; find the editor-schema one
    ext_routes = [r for r in cms._extension_routes if "/api/editor-schema" in r["path"]]
    assert len(ext_routes) == 1, "Expected exactly one /api/editor-schema extension route"


@pytest.mark.anyio
async def test_editor_schema_endpoint_reachable():
    """GET /api/editor-schema returns 200 with a nodes key."""
    cms, _ = _build_cms_and_editor()
    app = Starlette(routes=[Mount("/", app=cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/api/editor-schema")

    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "blockTypes" in data


@pytest.mark.anyio
async def test_shell_serves_html():
    """GET /shell returns 200 with a DOCTYPE html document."""
    _, editor = _build_cms_and_editor()
    app = Starlette(routes=[Mount("/editor", app=editor.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/editor/shell")

    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text


@pytest.mark.anyio
async def test_shell_injects_config():
    """The shell HTML contains the __EDITOR_CONFIG__ bootstrap object."""
    _, editor = _build_cms_and_editor()
    app = Starlette(routes=[Mount("/editor", app=editor.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/editor/shell")

    assert "__EDITOR_CONFIG__" in resp.text


@pytest.mark.anyio
async def test_shell_injects_media_base_null():
    """Shell HTML contains mediaBase: null when Editor has no media_base."""
    from starlette_cms.app import CMS
    from starlette_editor.app import Editor

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    editor = Editor(cms=cms, mount_path="/editor")  # no media_base

    app = Starlette(routes=[Mount("/editor", app=editor.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/editor/shell")

    assert resp.status_code == 200
    assert "mediaBase: null" in resp.text


@pytest.mark.anyio
async def test_shell_injects_media_base():
    """Shell HTML contains the configured media_base path."""
    from starlette_cms.app import CMS
    from starlette_editor.app import Editor

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    editor = Editor(cms=cms, mount_path="/editor", media_base="/media")

    app = Starlette(routes=[Mount("/editor", app=editor.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/editor/shell")

    assert resp.status_code == 200
    assert '"/media"' in resp.text
