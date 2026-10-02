"""
MCP server implementation for mediakit.

All tools are thin wrappers around the mediakit HTTP API.
No business logic lives here — only tool definitions and httpx calls.
"""

from __future__ import annotations

import difflib
from typing import Annotated, Any

import httpx
from pydantic import Field, model_validator

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The MCP server requires the 'mcp' extra. Install with: pip install mediakit[mcp]"
    ) from exc


DEFAULT_LIST_LIMIT = 10
MAX_LIST_LIMIT = 50

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
UPDATE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
DELETE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

LIMIT_DESCRIPTION = (
    f"Max assets to return, 1-{MAX_LIST_LIMIT} (default {DEFAULT_LIST_LIMIT}). "
    "Use offset to page through more."
)
OFFSET_DESCRIPTION = "Assets to skip. Use `next_offset` from the previous page."


def _error(message: str, hint: str | None = None) -> dict[str, Any]:
    """Build an error payload: what went wrong, plus what to try next."""
    payload: dict[str, Any] = {"error": message}
    if hint:
        payload["hint"] = hint
    return payload


def _page(data: dict[str, Any], limit: int, offset: int) -> dict[str, Any]:
    """
    Add pagination metadata to a list response.

    The API does not report a total, so ``has_more`` is true whenever the page
    came back full; the next page may then turn out to be empty.
    """
    assets: list[dict[str, Any]] = data.get("assets", [])
    returned = len(assets)
    has_more = returned >= limit
    return {
        **data,
        "assets": assets,
        "has_more": has_more,
        "limit": limit,
        "next_offset": offset + returned if has_more else None,
        "offset": offset,
        "returned": returned,
    }


def _unknown_parameter_message(tool_name: str, unknown: list[str], valid: list[str]) -> str:
    """Explain unknown tool arguments, suggesting the closest valid name."""
    parts: list[str] = []
    for name in unknown:
        close = difflib.get_close_matches(name, valid, n=1, cutoff=0.5)
        suggestion = f" Did you mean `{close[0]}`?" if close else ""
        parts.append(f"Unknown parameter `{name}` for {tool_name}.{suggestion}")
    valid_list = ", ".join(f"`{v}`" for v in valid) or "(none)"
    return " ".join(parts) + f" Valid parameters: {valid_list}."


def _reject_unknown_arguments(mcp: FastMCP) -> None:
    """
    Make every registered tool fail loudly on unknown arguments.

    FastMCP validates arguments with a pydantic model whose default is to
    silently ignore extra keys, so a misnamed filter was dropped and the call
    ran unfiltered.  Each tool's argument model is replaced by a subclass whose
    ``before`` validator raises a message naming the closest valid parameter.
    """
    for tool in mcp._tool_manager.list_tools():
        arg_model = tool.fn_metadata.arg_model
        valid = sorted(arg_model.model_fields)
        tool_name = tool.name

        def _check(cls: Any, data: Any, _tool: str = tool_name, _valid: list[str] = valid) -> Any:
            if isinstance(data, dict):
                unknown = sorted(set(data) - set(_valid))
                if unknown:
                    raise ValueError(_unknown_parameter_message(_tool, unknown, _valid))
            return data

        tool.fn_metadata.arg_model = type(
            arg_model.__name__,
            (arg_model,),
            {"check_unknown_arguments": model_validator(mode="before")(classmethod(_check))},
        )
        tool.parameters["additionalProperties"] = False


def build_mcp_server(base_url: str, api_key: str | None = None) -> FastMCP:
    """
    Build and return a FastMCP server wired to the mediakit HTTP API.

    :param base_url: Base URL of the deployed mediakit instance,
        e.g. ``https://mysite.com/media``.  Must not have a trailing slash.
    :param api_key: API key for ``Authorization: Bearer`` header on all
        requests.  Pass ``None`` when running without auth.

    All tools share one httpx.AsyncClient (connection-pooled).  The client is
    created lazily on the first tool call so the server can be imported without
    making any network connections.
    """

    _client: httpx.AsyncClient | None = None

    def _get_client() -> httpx.AsyncClient:
        nonlocal _client
        if _client is None or _client.is_closed:
            headers: dict[str, str] = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            _client = httpx.AsyncClient(
                base_url=base_url,
                headers=headers,
                timeout=30.0,
            )
        return _client

    def _read_headers() -> dict[str, str]:
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    mcp = FastMCP(
        name="mediakit",
        instructions=(
            "Tools for managing media assets in a mediakit instance.\n"
            "Workflow:\n"
            "1. list_assets (browse) or search_assets (filter by content_type / tags) to "
            "find assets. Keep limit small and page with offset / next_offset.\n"
            "2. get_asset(key) for one asset's metadata and a presigned download URL.\n"
            "3. get_iiif_url(key, size=...) to build an embeddable derivative image URL; "
            "it makes no network call.\n"
            "4. update_asset to set alt_text or tags. delete_asset permanently removes "
            "the file and its catalog entry; only call it when asked.\n"
            "Parameter names are exact: an unknown parameter is rejected with a "
            "suggestion, not ignored."
        ),
    )

    # ------------------------------------------------------------------
    # Asset read tools
    # ------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    async def list_assets(
        limit: Annotated[
            int, Field(ge=1, le=MAX_LIST_LIMIT, description=LIMIT_DESCRIPTION)
        ] = DEFAULT_LIST_LIMIT,
        offset: Annotated[int, Field(ge=0, description=OFFSET_DESCRIPTION)] = 0,
    ) -> dict[str, Any]:
        """
        Browse the asset catalog, one page at a time.

        Use search_assets instead when you want to filter by content type or tag.
        Each asset includes its `key`, which get_asset, update_asset and
        delete_asset take.

        Returns `assets` plus `limit`, `offset`, `returned`, `has_more` and
        `next_offset` (pass it as `offset` to get the next page).
        """
        client = _get_client()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        r = await client.get("/assets", params=params, headers=_read_headers())
        r.raise_for_status()
        return _page(r.json(), limit, offset)

    @mcp.tool(annotations=READ_ONLY)
    async def search_assets(
        content_type: Annotated[
            str | None, Field(description='MIME type filter, e.g. "image/webp".')
        ] = None,
        tags: Annotated[
            str | None,
            Field(description='Comma-separated tag filter, e.g. "nature,landscape".'),
        ] = None,
        limit: Annotated[
            int, Field(ge=1, le=MAX_LIST_LIMIT, description=LIMIT_DESCRIPTION)
        ] = DEFAULT_LIST_LIMIT,
        offset: Annotated[int, Field(ge=0, description=OFFSET_DESCRIPTION)] = 0,
    ) -> dict[str, Any]:
        """
        Find assets by content type and/or tags, one page at a time.

        Both filters are optional; with neither it behaves like list_assets.
        Returns the same shape as list_assets, including pagination metadata.
        """
        client = _get_client()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if content_type is not None:
            params["content_type"] = content_type
        if tags is not None:
            params["tags"] = tags
        r = await client.get("/assets", params=params, headers=_read_headers())
        r.raise_for_status()
        return _page(r.json(), limit, offset)

    @mcp.tool(annotations=READ_ONLY)
    async def get_asset(
        key: Annotated[
            str,
            Field(
                description=(
                    'The asset storage key, e.g. "originals/abc123/photo.jpg". '
                    "Get keys from list_assets or search_assets."
                )
            ),
        ],
    ) -> dict[str, Any]:
        """
        Return one asset's metadata and a presigned download URL.

        The download URL is temporary. For an image to embed in a page, use
        get_iiif_url instead.
        """
        client = _get_client()
        r = await client.get(f"/assets/{key}", headers=_read_headers())
        if r.status_code == 404:
            return _error(
                f"Asset {key!r} not found",
                hint="Use a `key` exactly as returned by list_assets or search_assets.",
            )
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Asset write tools
    # ------------------------------------------------------------------

    @mcp.tool(annotations=UPDATE)
    async def update_asset(
        key: Annotated[str, Field(description="The asset storage key from list_assets.")],
        alt_text: Annotated[
            str | None, Field(description="New alt text (accessibility / SEO).")
        ] = None,
        tags: Annotated[
            list[str] | None,
            Field(description="New tag list. REPLACES all existing tags."),
        ] = None,
    ) -> dict[str, Any]:
        """
        Update an asset's metadata (PATCH: only the fields you provide change).

        Safe to repeat. Note that `tags` replaces the whole list; call get_asset
        first if you want to add a tag without losing the existing ones.
        """
        client = _get_client()
        payload: dict[str, Any] = {}
        if alt_text is not None:
            payload["alt_text"] = alt_text
        if tags is not None:
            payload["tags"] = tags
        r = await client.patch(f"/assets/{key}", json=payload)
        if r.status_code == 404:
            return _error(
                f"Asset {key!r} not found",
                hint="Use a `key` exactly as returned by list_assets or search_assets.",
            )
        r.raise_for_status()
        return r.json()

    @mcp.tool(annotations=DELETE)
    async def delete_asset(
        key: Annotated[str, Field(description="The asset storage key from list_assets.")],
    ) -> dict[str, Any]:
        """
        Permanently delete an asset from the storage bucket and the catalog.

        This cannot be undone and breaks any page that embeds the asset. Only call
        it when asked to delete.
        """
        client = _get_client()
        r = await client.delete(f"/assets/{key}")
        if r.status_code == 404:
            return _error(
                f"Asset {key!r} not found",
                hint="Use a `key` exactly as returned by list_assets; it may already be deleted.",
            )
        r.raise_for_status()
        return {"deleted": True, "key": key}

    # ------------------------------------------------------------------
    # IIIF URL construction (pure, no HTTP call)
    # ------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    async def get_iiif_url(
        key: str,
        region: str = "full",
        size: str = "max",
        rotation: str = "0",
        quality: str = "default",
        format: str = "webp",
    ) -> str:
        """
        Construct a IIIF Image API URL for a derivative of the given asset.

        No HTTP call is made — this is a pure URL construction helper.
        Use the returned URL in HTML ``<img>`` tags or pass it to other tools.

        :param key: The asset's storage key.
        :param region: IIIF region parameter (default ``"full"``).
        :param size: IIIF size parameter (default ``"max"``).
        :param rotation: IIIF rotation parameter (default ``"0"``).
        :param quality: IIIF quality parameter (default ``"default"``).
        :param format: Output format extension (default ``"webp"``).

        Example — thumbnail at 200 px wide::

            get_iiif_url(key="originals/abc/photo.jpg", size="200,")
            # → "https://mysite.com/media/iiif/originals/abc/photo.jpg/full/200,/0/default.webp"
        """
        return f"{base_url}/iiif/{key}/{region}/{size}/{rotation}/{quality}.{format}"

    _reject_unknown_arguments(mcp)

    return mcp
