"""Tests for the gateway MCP server (starlette_cms_gateways/mcp/server.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest
from starlette_cms_gateways.mcp.server import (
    MAX_LIMIT,
    MAX_RESPONSE_CHARS,
    TOOL_GET_RECENT_GATEWAY_ITEMS,
    build_gateway_mcp_server,
)

pytest_plugins = ["anyio"]


def _doc(doc_id: str) -> dict[str, Any]:
    return {
        "id": doc_id,
        "doc_type": "spotify_liked_song",
        "slug": f"song-{doc_id}",
        "published": True,
        "body": {"title": "A song", "blob": "x" * 50_000},
    }


async def _call(arguments: dict[str, Any], documents: list[dict[str, Any]]):
    server = build_gateway_mcp_server(base_url="http://testcms.local")
    handler = server.request_handlers[CallToolRequest]
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=TOOL_GET_RECENT_GATEWAY_ITEMS, arguments=arguments),
    )
    payload = {"documents": documents, "total": len(documents)}
    with patch(
        "starlette_cms_gateways.client.CMSClient.list_documents",
        new_callable=AsyncMock,
        return_value=payload,
    ) as mock_list:
        result = await handler(request)
    return result.root, mock_list


@pytest.mark.anyio
async def test_returns_summaries_without_bodies():
    result, _ = await _call({"block_type": "spotify_liked_song"}, [_doc("a"), _doc("b")])

    text = result.content[0].text
    assert not result.isError
    assert "A song" in text
    assert "xxxx" not in text


@pytest.mark.anyio
async def test_default_limit_is_small():
    _, mock_list = await _call({"block_type": "spotify_liked_song"}, [])

    assert mock_list.call_args.kwargs["limit"] == 10


@pytest.mark.anyio
async def test_unknown_parameter_is_rejected_with_suggestion():
    result, mock_list = await _call({"block_type": "spotify_liked_song", "max_limit": 5}, [])

    assert result.isError
    assert "Did you mean `limit`?" in result.content[0].text
    mock_list.assert_not_called()


@pytest.mark.anyio
async def test_limit_above_maximum_is_rejected():
    result, mock_list = await _call(
        {"block_type": "spotify_liked_song", "limit": MAX_LIMIT + 1}, []
    )

    assert result.isError
    mock_list.assert_not_called()


@pytest.mark.anyio
async def test_response_is_capped_with_notice():
    docs = [dict(_doc(str(i)), body={"title": "t" * 5_000}) for i in range(50)]
    result, _ = await _call({"block_type": "spotify_liked_song", "limit": 50}, docs)

    text = result.content[0].text
    assert "[truncated at" in text
    assert len(text) < MAX_RESPONSE_CHARS + 200


@pytest.mark.anyio
async def test_tool_is_annotated_read_only():
    server = build_gateway_mcp_server(base_url="http://testcms.local")
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))

    tool = result.root.tools[0]
    assert tool.annotations.readOnlyHint is True
    assert tool.inputSchema["properties"]["limit"]["maximum"] == MAX_LIMIT
