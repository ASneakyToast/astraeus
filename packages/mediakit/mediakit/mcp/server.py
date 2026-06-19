"""
MCP server implementation for mediakit.

All tools are thin wrappers around the mediakit HTTP API.
No business logic lives here — only tool definitions and httpx calls.
"""

from __future__ import annotations

from typing import Any

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The MCP server requires the 'mcp' extra. Install with: pip install mediakit[mcp]"
    ) from exc


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
            "Tools for managing media assets in a mediakit instance. "
            "Use list_assets or search_assets to discover assets, "
            "get_asset to retrieve metadata and a presigned download URL, "
            "get_iiif_url to construct derivative image URLs for embedding, "
            "update_asset to add or change metadata (alt_text, tags), "
            "delete_asset to permanently remove an asset from storage and catalog."
        ),
    )

    # ------------------------------------------------------------------
    # Asset read tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_assets(
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Return a paginated list of all assets in the catalog.

        Returns a dict with keys:
        - ``assets``: list of asset objects
        - ``limit``: the limit that was applied
        - ``offset``: the offset that was applied

        :param limit: Max number of assets to return (default 20).
        :param offset: Number of assets to skip for pagination (default 0).
        """
        client = _get_client()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        r = await client.get("/assets", params=params, headers=_read_headers())
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def search_assets(
        content_type: str | None = None,
        tags: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Search assets by content type and/or tags.

        Returns the same shape as list_assets.  Both filters are optional —
        omitting both is equivalent to list_assets.

        :param content_type: MIME type filter, e.g. ``"image/webp"``.
        :param tags: Comma-separated tag filter, e.g. ``"nature,landscape"``.
        :param limit: Max number of assets to return (default 20).
        :param offset: Number of assets to skip for pagination (default 0).
        """
        client = _get_client()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if content_type is not None:
            params["content_type"] = content_type
        if tags is not None:
            params["tags"] = tags
        r = await client.get("/assets", params=params, headers=_read_headers())
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def get_asset(key: str) -> dict[str, Any]:
        """
        Return a single asset's metadata and a presigned download URL.

        :param key: The asset's storage key
            (e.g. ``"originals/abc123/photo.jpg"``).
            Obtain keys from list_assets or search_assets.
        """
        client = _get_client()
        r = await client.get(f"/assets/{key}", headers=_read_headers())
        if r.status_code == 404:
            return {"error": f"Asset {key!r} not found"}
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Asset write tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def update_asset(
        key: str,
        alt_text: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update metadata for an existing asset (PATCH semantics — only the
        fields you provide are changed; omitted fields are left as-is).

        :param key: The asset's storage key.
        :param alt_text: New alt text for the asset (accessibility / SEO).
        :param tags: New list of tags.  Replaces the existing tag list entirely.
        """
        client = _get_client()
        payload: dict[str, Any] = {}
        if alt_text is not None:
            payload["alt_text"] = alt_text
        if tags is not None:
            payload["tags"] = tags
        r = await client.patch(f"/assets/{key}", json=payload)
        if r.status_code == 404:
            return {"error": f"Asset {key!r} not found"}
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def delete_asset(key: str) -> dict[str, Any]:
        """
        Permanently delete an asset from both the storage bucket and the catalog.

        :param key: The asset's storage key.
        """
        client = _get_client()
        r = await client.delete(f"/assets/{key}")
        if r.status_code == 404:
            return {"error": f"Asset {key!r} not found"}
        r.raise_for_status()
        return {"deleted": True, "key": key}

    # ------------------------------------------------------------------
    # IIIF URL construction (pure, no HTTP call)
    # ------------------------------------------------------------------

    @mcp.tool()
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

    return mcp
