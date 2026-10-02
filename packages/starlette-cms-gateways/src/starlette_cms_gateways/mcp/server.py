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

import difflib
import json
from typing import Any

DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# Hard cap on the size of the tool response, in characters.
MAX_RESPONSE_CHARS = 20_000

TOOL_GET_RECENT_GATEWAY_ITEMS = "get_recent_gateway_items"
VALID_PARAMETERS = ["block_type", "limit"]


def _unknown_parameter_message(tool_name: str, unknown: list[str], valid: list[str]) -> str:
    """Explain unknown tool arguments, suggesting the closest valid name."""
    parts: list[str] = []
    for name in unknown:
        close = difflib.get_close_matches(name, valid, n=1, cutoff=0.5)
        suggestion = f" Did you mean `{close[0]}`?" if close else ""
        parts.append(f"Unknown parameter `{name}` for {tool_name}.{suggestion}")
    valid_list = ", ".join(f"`{v}`" for v in valid)
    return " ".join(parts) + f" Valid parameters: {valid_list}."


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
        from mcp.types import TextContent, Tool, ToolAnnotations
    except ImportError as exc:
        raise ImportError(
            "MCP server requires the 'mcp' extra. "
            "Install with: pip install starlette-cms-gateways[mcp]"
        ) from exc

    from starlette_cms.mcp.server import summarize_document

    from starlette_cms_gateways.client import CMSClient

    client = CMSClient(base_url=base_url.rstrip("/"), api_key=api_key)
    server: Server = Server("starlette-cms-gateways")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=TOOL_GET_RECENT_GATEWAY_ITEMS,
                description=(
                    "List recently synced CMS documents for a specific gateway service, "
                    "newest first, as short summaries WITHOUT bodies (id, doc_type, slug, "
                    "title, status, dates, excerpt). Pass the block_type used by that "
                    "gateway. To read one item in full, use the starlette-cms get_document "
                    "tool with its id. Output is capped at "
                    f"{MAX_RESPONSE_CHARS} characters."
                ),
                annotations=ToolAnnotations(
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
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
                            "description": (
                                f"Maximum number of documents to return, 1-{MAX_LIMIT} "
                                f"(default {DEFAULT_LIMIT})."
                            ),
                            "default": DEFAULT_LIMIT,
                            "minimum": 1,
                            "maximum": MAX_LIMIT,
                        },
                    },
                    "required": ["block_type"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == TOOL_GET_RECENT_GATEWAY_ITEMS:
            unknown = sorted(set(arguments) - set(VALID_PARAMETERS))
            if unknown:
                raise ValueError(_unknown_parameter_message(name, unknown, VALID_PARAMETERS))

            block_type = arguments.get("block_type", "")
            limit = int(arguments.get("limit", DEFAULT_LIMIT))
            data = await client.list_documents(doc_type=block_type, limit=limit)
            docs = [summarize_document(d).model_dump() for d in data.get("documents", [])]
            total = data.get("total", 0)
            text = (
                f"{total} document(s) of type {block_type!r} "
                f"(showing {len(docs)}):\n" + json.dumps(docs, indent=2, default=str)
            )
            if len(text) > MAX_RESPONSE_CHARS:
                text = (
                    text[:MAX_RESPONSE_CHARS]
                    + f"\n[truncated at {MAX_RESPONSE_CHARS} characters; "
                    "lower `limit` to see fewer items]"
                )
            return [TextContent(type="text", text=text)]

        return [TextContent(type="text", text=f"Unknown tool: {name!r}")]

    return server
