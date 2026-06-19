"""
CLI entry point — ``mediakit mcp serve``

Examples::

    # Start the MCP server connected to a local dev instance
    mediakit mcp serve --url http://localhost:8000/media

    # Connect to production with an API key
    mediakit mcp serve --url https://mysite.com/media --api-key secret
"""

from __future__ import annotations

import click

# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
def main():
    """mediakit management commands."""


# ---------------------------------------------------------------------------
# mcp group
# ---------------------------------------------------------------------------


@main.group()
def mcp():
    """MCP server commands (requires mediakit[mcp])."""


@mcp.command("serve")
@click.option(
    "--url",
    required=True,
    help="Base URL of the mediakit instance (e.g. https://mysite.com/media).",
)
@click.option(
    "--api-key",
    default=None,
    envvar="MEDIAKIT_API_KEY",
    show_default="MEDIAKIT_API_KEY env var",
    help="API key for Authorization: Bearer header.",
)
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    show_default=True,
    help="MCP transport protocol.",
)
def mcp_serve(url: str, api_key: str | None, transport: str) -> None:
    """
    Start the mediakit MCP server.

    Connects to the mediakit instance at --url and exposes its asset API
    as agent-callable tools.  Run locally; point at a deployed instance
    over HTTP.

    Examples::

        # Connect to a local dev server
        mediakit mcp serve --url http://localhost:8000/media

        # Connect to production with an API key
        mediakit mcp serve --url https://mysite.com/media --api-key secret
    """
    try:
        from mediakit.mcp.server import build_mcp_server
    except ImportError:
        raise click.ClickException(
            "MCP server requires the 'mcp' extra. Install with: pip install mediakit[mcp]"
        )

    server = build_mcp_server(base_url=url.rstrip("/"), api_key=api_key)
    server.run(transport=transport)  # type: ignore[arg-type]
