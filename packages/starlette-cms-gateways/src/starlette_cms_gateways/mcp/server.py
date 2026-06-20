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

- ``list_gateway_syncs`` — list all services in the sync state singleton
- ``get_recent_gateway_items`` — list recently synced documents for a service
- ``trigger_gateway_sync`` — invoke a registered gateway's ``sync()`` method
  (requires the gateway class to be importable in the server's process)
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
                name="list_gateway_syncs",
                description=(
                    "List all gateway services that have recorded sync state in this CMS, "
                    "along with their last-synced timestamp and result counts."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            ),
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

        if name == "list_gateway_syncs":
            state = await client.get_gateway_status()
            services = state.get("services") or {}
            if not services:
                return [TextContent(type="text", text="No sync state recorded yet.")]
            lines = []
            for svc_name, svc_data in sorted(services.items()):
                last = svc_data.get("last_synced", "never")
                r = svc_data.get("last_result") or {}
                lines.append(
                    f"{svc_name}: last_synced={last}  "
                    f"created={r.get('created', 0)}  "
                    f"updated={r.get('updated', 0)}  "
                    f"skipped={r.get('skipped', 0)}"
                )
            return [TextContent(type="text", text="\n".join(lines))]

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
