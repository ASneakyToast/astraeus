"""
Tests for ProseMirrorBridge.generate_schema().

Each test uses an in-process CMS with a fresh SQLite :memory: database.
We avoid pytest fixtures here so tests are fully self-contained and fast.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount

pytest_plugins = ["anyio"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_cms_with_blocks():
    """Return a (cms, bridge) pair with a representative set of field types."""
    from starlette_cms.app import CMS
    from starlette_cms.fields import (
        BoolField,
        NumberField,
        RichTextField,
        SelectField,
        TextField,
    )
    from starlette_cms.prosemirror.bridge import ProseMirrorBridge

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)

    @cms.block("article")
    class Article:
        title: str = TextField(label="Title", required=True)
        body: dict = RichTextField(label="Body")
        category: str = SelectField(choices=["news", "blog"])
        views: float = NumberField(min_value=0)
        active: bool = BoolField()

    bridge = ProseMirrorBridge(cms.registry)
    return cms, bridge


def _build_empty_cms():
    """Return a (cms, bridge) pair with no blocks registered."""
    from starlette_cms.app import CMS
    from starlette_cms.prosemirror.bridge import ProseMirrorBridge

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    bridge = ProseMirrorBridge(cms.registry)
    return cms, bridge


# ---------------------------------------------------------------------------
# Schema structure
# ---------------------------------------------------------------------------


def test_generate_schema_returns_dict_with_nodes_and_marks():
    _, bridge = _build_cms_with_blocks()
    schema = bridge.generate_schema()
    assert isinstance(schema, dict)
    assert "nodes" in schema
    assert "marks" in schema
    assert "blockTypes" in schema


def test_standard_prosemirror_nodes_present():
    _, bridge = _build_cms_with_blocks()
    nodes = bridge.generate_schema()["nodes"]
    standard = ("doc", "paragraph", "text", "heading", "blockquote", "code_block", "hard_break")
    for expected in standard:
        assert expected in nodes, f"Expected standard node {expected!r} missing from nodes"


def test_standard_marks_present():
    _, bridge = _build_cms_with_blocks()
    marks = bridge.generate_schema()["marks"]
    for expected in ("strong", "em", "code", "link"):
        assert expected in marks, f"Expected mark {expected!r} missing from marks"


# ---------------------------------------------------------------------------
# blockTypes
# ---------------------------------------------------------------------------


def test_block_types_key_contains_registered_blocks():
    _, bridge = _build_cms_with_blocks()
    block_types = bridge.generate_schema()["blockTypes"]
    assert "article" in block_types


def test_rich_text_field_has_field_type_rich_text():
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert fields["body"]["field_type"] == "rich_text"


def test_text_field_has_field_type_text():
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert fields["title"]["field_type"] == "text"


def test_select_field_has_choices():
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert fields["category"]["choices"] == ["news", "blog"]


def test_number_field_has_min_value():
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert fields["views"]["min_value"] == 0


def test_bool_field_has_default():
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert fields["active"]["default"] is False


def test_block_type_discriminator_not_in_fields():
    """block_type is an injected discriminator field — it must not appear in blockTypes fields."""
    _, bridge = _build_cms_with_blocks()
    fields = bridge.generate_schema()["blockTypes"]["article"]["fields"]
    assert "block_type" not in fields


# ---------------------------------------------------------------------------
# Empty registry
# ---------------------------------------------------------------------------


def test_empty_registry_returns_base_schema():
    _, bridge = _build_empty_cms()
    schema = bridge.generate_schema()
    assert "doc" in schema["nodes"]
    assert "paragraph" in schema["nodes"]
    assert schema["blockTypes"] == {}


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_schema_endpoint_returns_200():
    from starlette_cms.app import CMS
    from starlette_cms.prosemirror.bridge import ProseMirrorBridge

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)
    bridge = ProseMirrorBridge(cms.registry)
    cms.register_extension_route(
        path="/api/editor-schema",
        endpoint=bridge.schema_endpoint,
        methods=["GET"],
        name="editor_schema_test",
    )

    app = Starlette(routes=[Mount("/", app=cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/api/editor-schema")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_schema_endpoint_json_is_valid():
    from starlette_cms.app import CMS
    from starlette_cms.fields import RichTextField, TextField
    from starlette_cms.prosemirror.bridge import ProseMirrorBridge

    cms = CMS(database_url="sqlite:///:memory:", auth="none", read_auth=False)

    @cms.block("post")
    class Post:
        title: str = TextField(required=True)
        body: dict = RichTextField()

    bridge = ProseMirrorBridge(cms.registry)
    cms.register_extension_route(
        path="/api/editor-schema",
        endpoint=bridge.schema_endpoint,
        methods=["GET"],
        name="editor_schema_test2",
    )

    app = Starlette(routes=[Mount("/", app=cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        resp = await client.get("/api/editor-schema")

    data = resp.json()
    assert "nodes" in data
    assert "marks" in data
    assert "blockTypes" in data
    assert data["blockTypes"]["post"]["fields"]["body"]["field_type"] == "rich_text"
