"""
starlette-cms MCP server — thin HTTP client wrapper (ADR 005).

Install::

    pip install starlette-cms[mcp]

Run::

    starlette-cms mcp serve --url https://mysite.com/cms --api-key secret

This starts a local MCP server (stdio transport by default) that exposes the
starlette-cms HTTP API as agent-callable tools.  The server is a plain HTTP
client — it contains no business logic, only tool definitions and httpx calls.
"""

from starlette_cms.mcp.server import build_mcp_server

__all__ = ["build_mcp_server"]
