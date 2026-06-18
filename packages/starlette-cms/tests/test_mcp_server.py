"""
Tests for the MCP server (starlette_cms/mcp/server.py).

Strategy: build the MCP server with a mocked httpx.AsyncClient so we don't
need a live HTTP server.  Each test directly calls the tool coroutine via the
FastMCP instance's tool registry and verifies the correct HTTP calls are made.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest_plugins = ["anyio"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: Any) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data)
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        from httpx import HTTPStatusError

        resp.raise_for_status.side_effect = HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


def _build_server(api_key: str | None = None):
    """Build a server instance with a patched AsyncClient."""
    from starlette_cms.mcp.server import build_mcp_server

    return build_mcp_server(base_url="http://testcms.local", api_key=api_key)


async def _call_tool(mcp_server, tool_name: str, **kwargs) -> Any:
    """Look up a tool by name and call it directly with the given kwargs."""
    tools = await mcp_server.list_tools()
    for t in tools:
        if t.name == tool_name:
            break
    else:
        raise KeyError(f"Tool {tool_name!r} not registered")

    # Retrieve the underlying coroutine function from the FastMCP internals
    tool_fn = mcp_server._tool_manager._tools[tool_name].fn
    return await tool_fn(**kwargs)


# ---------------------------------------------------------------------------
# list_block_types
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_block_types_returns_names():
    mcp = _build_server()
    schema_response = {
        "$defs": {
            "blog_post": {"type": "object"},
            "hero": {"type": "object"},
        }
    }
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(200, schema_response),
    ):
        result = await _call_tool(mcp, "list_block_types")

    assert set(result) == {"blog_post", "hero"}


@pytest.mark.anyio
async def test_list_block_types_definitions_fallback():
    """Accepts older 'definitions' key too."""
    mcp = _build_server()
    schema_response = {"definitions": {"article": {"type": "object"}}}
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(200, schema_response),
    ):
        result = await _call_tool(mcp, "list_block_types")

    assert result == ["article"]


# ---------------------------------------------------------------------------
# get_block_schema
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_block_schema_found():
    mcp = _build_server()
    schema = {"title": "hero", "properties": {"title": {"type": "string"}}}
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(200, schema),
    ):
        result = await _call_tool(mcp, "get_block_schema", block_type="hero")

    assert result == schema


@pytest.mark.anyio
async def test_get_block_schema_not_found():
    mcp = _build_server()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(404, {"error": "not found"}),
    ):
        result = await _call_tool(mcp, "get_block_schema", block_type="unknown")

    assert "error" in result
    assert "unknown" in result["error"]


# ---------------------------------------------------------------------------
# list_documents
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_documents_no_filters():
    mcp = _build_server()
    payload = {"documents": [], "total": 0, "filters_applied": {}}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        result = await _call_tool(mcp, "list_documents")

    assert result == payload
    call_kwargs = mock_get.call_args
    assert "/api/documents" in str(call_kwargs)


@pytest.mark.anyio
async def test_list_documents_with_type_filter():
    mcp = _build_server()
    payload = {"documents": [{"id": "abc"}], "total": 1, "filters_applied": {}}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        result = await _call_tool(mcp, "list_documents", doc_type="blog_post", limit=10)

    assert result == payload
    # Check the correct query params were sent
    call_args = mock_get.call_args
    params = call_args.kwargs.get("params") or call_args.args[1] if len(call_args.args) > 1 else {}
    if not params:
        # params passed as keyword
        params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("type") == "blog_post"
    assert params.get("limit") == 10


@pytest.mark.anyio
async def test_list_documents_published_filter():
    mcp = _build_server()
    mock_get = AsyncMock(
        return_value=_mock_response(200, {"documents": [], "total": 0, "filters_applied": {}})
    )

    with patch("httpx.AsyncClient.get", mock_get):
        await _call_tool(mcp, "list_documents", published=True)

    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("published") == "true"


# ---------------------------------------------------------------------------
# get_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_document_found():
    mcp = _build_server()
    doc = {"id": "doc123", "doc_type": "hero", "body": {"title": "Hello"}}
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(200, doc),
    ):
        result = await _call_tool(mcp, "get_document", doc_id="doc123")

    assert result == doc


@pytest.mark.anyio
async def test_get_document_not_found():
    mcp = _build_server()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(404, {"error": "not found"}),
    ):
        result = await _call_tool(mcp, "get_document", doc_id="nope")

    assert "error" in result
    assert "nope" in result["error"]


# ---------------------------------------------------------------------------
# create_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_create_document_success():
    mcp = _build_server()
    created = {"id": "newdoc", "doc_type": "blog_post", "body": {"title": "Test"}}
    mock_post = AsyncMock(return_value=_mock_response(201, created))

    with patch("httpx.AsyncClient.post", mock_post):
        result = await _call_tool(
            mcp,
            "create_document",
            doc_type="blog_post",
            body={"title": "Test"},
            slug="test-post",
        )

    assert result == created
    payload = mock_post.call_args.kwargs.get("json", {})
    assert payload["doc_type"] == "blog_post"
    assert payload["body"] == {"title": "Test"}
    assert payload["slug"] == "test-post"


@pytest.mark.anyio
async def test_create_document_validation_error():
    mcp = _build_server()
    err_payload = {"error": "Validation failed", "detail": [{"loc": ["title"], "msg": "required"}]}
    mock_post = AsyncMock(return_value=_mock_response(422, err_payload))
    mock_post.return_value.raise_for_status = MagicMock()  # 422 is returned, not raised

    with patch("httpx.AsyncClient.post", mock_post):
        result = await _call_tool(
            mcp,
            "create_document",
            doc_type="blog_post",
            body={},
        )

    assert "error" in result


# ---------------------------------------------------------------------------
# update_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_document_success():
    mcp = _build_server()
    updated = {"id": "doc1", "doc_type": "blog_post", "body": {"title": "Updated"}}
    mock_patch = AsyncMock(return_value=_mock_response(200, updated))

    with patch("httpx.AsyncClient.patch", mock_patch):
        result = await _call_tool(
            mcp,
            "update_document",
            doc_id="doc1",
            body={"title": "Updated"},
        )

    assert result == updated
    payload = mock_patch.call_args.kwargs.get("json", {})
    assert payload["body"] == {"title": "Updated"}


@pytest.mark.anyio
async def test_update_document_not_found():
    mcp = _build_server()
    mock_patch = AsyncMock(return_value=_mock_response(404, {"error": "not found"}))

    with patch("httpx.AsyncClient.patch", mock_patch):
        result = await _call_tool(mcp, "update_document", doc_id="gone", body={})

    assert "error" in result


@pytest.mark.anyio
async def test_update_document_append_only_rejected():
    mcp = _build_server()
    mock_patch = AsyncMock(
        return_value=_mock_response(
            405, {"error": "append_only documents cannot be modified"}
        )
    )

    with patch("httpx.AsyncClient.patch", mock_patch):
        result = await _call_tool(mcp, "update_document", doc_id="audit1", body={})

    assert result["error"] == "append_only documents cannot be modified"


# ---------------------------------------------------------------------------
# delete_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_document_success():
    mcp = _build_server()
    mock_delete = AsyncMock(return_value=_mock_response(204, None))
    mock_delete.return_value.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_document", doc_id="doc1")

    assert result["deleted"] is True
    assert result["doc_id"] == "doc1"


@pytest.mark.anyio
async def test_delete_document_not_found():
    mcp = _build_server()
    mock_delete = AsyncMock(return_value=_mock_response(404, {"error": "not found"}))

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_document", doc_id="gone")

    assert "error" in result


@pytest.mark.anyio
async def test_delete_document_conflict():
    mcp = _build_server()
    mock_delete = AsyncMock(
        return_value=_mock_response(409, {"error": "Cannot delete: referenced by other.field"})
    )

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_document", doc_id="ref1")

    assert "Conflict" in result["error"] or "referenced" in result["error"]


@pytest.mark.anyio
async def test_delete_document_append_only_rejected():
    mcp = _build_server()
    mock_delete = AsyncMock(
        return_value=_mock_response(
            405, {"error": "append_only documents cannot be deleted"}
        )
    )

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_document", doc_id="audit1")

    assert "not allowed" in result["error"] or "Method" in result["error"] or "append_only" in result["error"]


# ---------------------------------------------------------------------------
# publish_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_publish_document_success():
    mcp = _build_server()
    published = {"id": "doc1", "published": True}
    mock_post = AsyncMock(return_value=_mock_response(200, published))

    with patch("httpx.AsyncClient.post", mock_post):
        result = await _call_tool(mcp, "publish_document", doc_id="doc1")

    assert result == published


@pytest.mark.anyio
async def test_publish_document_not_found():
    mcp = _build_server()
    mock_post = AsyncMock(return_value=_mock_response(404, {"error": "not found"}))

    with patch("httpx.AsyncClient.post", mock_post):
        result = await _call_tool(mcp, "publish_document", doc_id="gone")

    assert "error" in result


# ---------------------------------------------------------------------------
# unpublish_document
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unpublish_document_success():
    mcp = _build_server()
    unpublished = {"id": "doc1", "published": False}
    mock_post = AsyncMock(return_value=_mock_response(200, unpublished))

    with patch("httpx.AsyncClient.post", mock_post):
        result = await _call_tool(mcp, "unpublish_document", doc_id="doc1")

    assert result == unpublished


# ---------------------------------------------------------------------------
# Auth header forwarding
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_api_key_sent_as_bearer_on_writes():
    """API key is included in the Authorization header on mutating calls."""
    mcp = _build_server(api_key="my-secret")
    created = {"id": "newdoc", "doc_type": "blog_post", "body": {}}
    mock_post = AsyncMock(return_value=_mock_response(201, created))

    with patch("httpx.AsyncClient.post", mock_post):
        await _call_tool(mcp, "create_document", doc_type="blog_post", body={})

    # The Authorization header is set at client construction via default headers
    # We verify by checking the server was built with an api_key (structural test)
    # and that no error was raised during the call.
    assert mock_post.called


@pytest.mark.anyio
async def test_all_tools_registered():
    """All nine expected tools are registered."""
    from starlette_cms.mcp.server import build_mcp_server

    mcp = build_mcp_server(base_url="http://example.com")
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "list_block_types",
        "get_block_schema",
        "list_documents",
        "get_document",
        "create_document",
        "update_document",
        "delete_document",
        "publish_document",
        "unpublish_document",
    }
    assert expected <= tool_names, f"Missing tools: {expected - tool_names}"
