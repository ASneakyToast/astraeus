"""
MCP server factory for starlette-cms-gateways.

Requires ``pip install starlette-cms-gateways[mcp]``.

Usage::

    from starlette_cms_gateways.mcp.server import build_gateway_mcp_server

    server = build_gateway_mcp_server(
        base_url="https://cms.example.com",
        api_key="secret",
    )
    server.run(transport="stdio")

Exposed tools:

- ``get_recent_gateway_items`` — list recently synced documents for a service
"""

from __future__ import annotations

from typing import Any


def build_gateway_mcp_server(
    *,
    base_url: str,
    api_key: str | None = None,
) -> Any:
    """
    Build and return an MCP server exposing gateway management tools.

    :param base_url: Base URL of the starlette-cms instance.
    :param api_key: Optional API key.
    :returns: A configured ``mcp.Server`` instance.  Call ``.run()`` to start.

    :raises ImportError: if the ``mcp`` package is not installed.
    """
    try:
        from mcp.server import Server
        from mcp.server.models import InitializationOptions
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the 'mcp' extra. "
            "Install with: pip install starlette-cms-gateways[mcp]"
        ) from exc

    from starlette_cms_gateways.client import CMSClient

    client = CMSClient(base_url=base_url.rstrip("/"), api_key=api_key)
    server: Server = Server("starlette-cms-gateways")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_recent_gateway_items",
                description=(
                    "List recently synced CMS documents for a specific gateway service. "
                    "Pass the block_type used by that gateway."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "block_type": {
                            "type": "string",
                            "description": (
                                "The CMS block type for this gateway's documents, "
                                "e.g. 'spotify_liked_song'."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of documents to return (default 20).",
                            "default": 20,
                        },
                    },
                    "required": ["block_type"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        import json

        if name == "get_recent_gateway_items":
            block_type = arguments.get("block_type", "")
            limit = int(arguments.get("limit", 20))
            data = await client.list_documents(doc_type=block_type, limit=limit)
            docs = data.get("documents", [])
            total = data.get("total", 0)
            text = (
                f"{total} document(s) of type {block_type!r} "
                f"(showing {len(docs)}):\n"
                + json.dumps(docs, indent=2, default=str)
            )
            return [TextContent(type="text", text=text)]

        return [TextContent(type="text", text=f"Unknown tool: {name!r}")]

    return server
