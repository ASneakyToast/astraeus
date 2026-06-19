"""
Tests for the MCP server (mediakit/mcp/server.py).

Strategy: build the MCP server with a mocked httpx.AsyncClient so we don't
need a live HTTP server.  Each test directly calls the tool coroutine via the
FastMCP instance's tool registry and verifies the correct HTTP calls are made.
"""

from __future__ import annotations

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
    """Build a server instance pointed at a test base URL."""
    from mediakit.mcp.server import build_mcp_server

    return build_mcp_server(base_url="http://testmedia.local", api_key=api_key)


async def _call_tool(mcp_server, tool_name: str, **kwargs) -> Any:
    """Look up a tool by name and call it directly with the given kwargs."""
    tools = await mcp_server.list_tools()
    for t in tools:
        if t.name == tool_name:
            break
    else:
        raise KeyError(f"Tool {tool_name!r} not registered")

    tool_fn = mcp_server._tool_manager._tools[tool_name].fn
    return await tool_fn(**kwargs)


# ---------------------------------------------------------------------------
# list_assets
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_list_assets_returns_page():
    mcp = _build_server()
    payload = {"assets": [{"key": "originals/abc/photo.jpg"}], "limit": 20, "offset": 0}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        result = await _call_tool(mcp, "list_assets")

    assert result == payload
    assert mock_get.called


@pytest.mark.anyio
async def test_list_assets_pagination():
    mcp = _build_server()
    payload = {"assets": [], "limit": 10, "offset": 20}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        result = await _call_tool(mcp, "list_assets", limit=10, offset=20)

    assert result == payload
    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("limit") == 10
    assert params.get("offset") == 20


# ---------------------------------------------------------------------------
# search_assets
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_assets_by_content_type():
    mcp = _build_server()
    payload = {"assets": [], "limit": 20, "offset": 0}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        await _call_tool(mcp, "search_assets", content_type="image/webp")

    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("content_type") == "image/webp"
    assert "tags" not in params


@pytest.mark.anyio
async def test_search_assets_by_tags():
    mcp = _build_server()
    payload = {"assets": [], "limit": 20, "offset": 0}
    mock_get = AsyncMock(return_value=_mock_response(200, payload))

    with patch("httpx.AsyncClient.get", mock_get):
        await _call_tool(mcp, "search_assets", tags="nature,landscape")

    params = mock_get.call_args.kwargs.get("params", {})
    assert params.get("tags") == "nature,landscape"
    assert "content_type" not in params


# ---------------------------------------------------------------------------
# get_asset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_asset_found():
    mcp = _build_server()
    asset = {
        "key": "originals/abc/photo.jpg",
        "content_type": "image/jpeg",
        "download_url": "https://bucket.example.com/originals/abc/photo.jpg?sig=...",
    }
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(200, asset),
    ):
        result = await _call_tool(mcp, "get_asset", key="originals/abc/photo.jpg")

    assert result == asset
    assert result["key"] == "originals/abc/photo.jpg"


@pytest.mark.anyio
async def test_get_asset_not_found():
    mcp = _build_server()
    with patch(
        "httpx.AsyncClient.get",
        new_callable=AsyncMock,
        return_value=_mock_response(404, {"error": "not found"}),
    ):
        result = await _call_tool(mcp, "get_asset", key="originals/nope/missing.jpg")

    assert "error" in result
    assert "originals/nope/missing.jpg" in result["error"]


# ---------------------------------------------------------------------------
# update_asset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_update_asset_success():
    mcp = _build_server()
    updated = {
        "key": "originals/abc/photo.jpg",
        "alt_text": "A beautiful sunset",
        "tags": ["nature", "sunset"],
    }
    mock_patch = AsyncMock(return_value=_mock_response(200, updated))

    with patch("httpx.AsyncClient.patch", mock_patch):
        result = await _call_tool(
            mcp,
            "update_asset",
            key="originals/abc/photo.jpg",
            alt_text="A beautiful sunset",
            tags=["nature", "sunset"],
        )

    assert result == updated
    payload = mock_patch.call_args.kwargs.get("json", {})
    assert payload["alt_text"] == "A beautiful sunset"
    assert payload["tags"] == ["nature", "sunset"]


@pytest.mark.anyio
async def test_update_asset_not_found():
    mcp = _build_server()
    mock_patch = AsyncMock(return_value=_mock_response(404, {"error": "not found"}))

    with patch("httpx.AsyncClient.patch", mock_patch):
        result = await _call_tool(
            mcp, "update_asset", key="originals/gone/missing.jpg", alt_text="test"
        )

    assert "error" in result
    assert "originals/gone/missing.jpg" in result["error"]


# ---------------------------------------------------------------------------
# delete_asset
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_asset_success():
    mcp = _build_server()
    mock_delete = AsyncMock(return_value=_mock_response(204, None))
    mock_delete.return_value.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_asset", key="originals/abc/photo.jpg")

    assert result["deleted"] is True
    assert result["key"] == "originals/abc/photo.jpg"


@pytest.mark.anyio
async def test_delete_asset_not_found():
    mcp = _build_server()
    mock_delete = AsyncMock(return_value=_mock_response(404, {"error": "not found"}))

    with patch("httpx.AsyncClient.delete", mock_delete):
        result = await _call_tool(mcp, "delete_asset", key="originals/gone/missing.jpg")

    assert "error" in result
    assert "originals/gone/missing.jpg" in result["error"]


# ---------------------------------------------------------------------------
# get_iiif_url
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_iiif_url_defaults():
    """No HTTP call; returns a well-formed IIIF URL with default params."""
    mcp = _build_server()
    key = "originals/abc/photo.jpg"

    result = await _call_tool(mcp, "get_iiif_url", key=key)

    assert result == f"http://testmedia.local/iiif/{key}/full/max/0/default.webp"


@pytest.mark.anyio
async def test_get_iiif_url_custom_params():
    """Custom region/size/format are reflected in the returned URL."""
    mcp = _build_server()
    key = "originals/abc/photo.jpg"

    result = await _call_tool(
        mcp,
        "get_iiif_url",
        key=key,
        region="square",
        size="200,",
        rotation="90",
        quality="color",
        format="jpg",
    )

    assert result == f"http://testmedia.local/iiif/{key}/square/200,/90/color.jpg"


# ---------------------------------------------------------------------------
# All tools registered
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_all_tools_registered():
    """All six expected tools are registered."""
    from mediakit.mcp.server import build_mcp_server

    mcp = build_mcp_server(base_url="http://example.com")
    tools = await mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "list_assets",
        "search_assets",
        "get_asset",
        "update_asset",
        "delete_asset",
        "get_iiif_url",
    }
    assert expected <= tool_names, f"Missing tools: {expected - tool_names}"
