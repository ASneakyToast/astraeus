"""
MCP server implementation for starlette-cms (ADR 005).

All tools are thin wrappers around the starlette-cms HTTP API.
No business logic lives here — only tool definitions and httpx calls.
"""

from __future__ import annotations

from typing import Any

import httpx

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The MCP server requires the 'mcp' extra. "
        "Install with: pip install starlette-cms[mcp]"
    ) from exc


def build_mcp_server(base_url: str, api_key: str | None = None) -> FastMCP:
    """
    Build and return a FastMCP server wired to the starlette-cms HTTP API.

    :param base_url: Base URL of the deployed starlette-cms instance,
        e.g. ``https://mysite.com/cms``.  Must not have a trailing slash.
    :param api_key: API key for ``Authorization: Bearer`` header on all
        mutating requests.  Pass ``None`` when the CMS is running in
        ``auth="none"`` mode.

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

    # Ensure any API key is included in read headers too (for read_auth=True CMSes)
    def _read_headers() -> dict[str, str]:
        if api_key:
            return {"Authorization": f"Bearer {api_key}"}
        return {}

    mcp = FastMCP(
        name="starlette-cms",
        instructions=(
            "Tools for managing content in a starlette-cms instance. "
            "Use list_block_types to discover what document types are available, "
            "get_block_schema to understand a type's fields, then create/update/delete "
            "documents as needed. Publish a document to make it publicly visible."
        ),
    )

    # ------------------------------------------------------------------
    # Schema tools (read-only, no auth required for most deployments)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_block_types() -> list[str]:
        """
        Return the names of all block types registered in this CMS.

        Use this first to discover what document types are available, then call
        get_block_schema(block_type) to see the fields for a specific type.
        """
        client = _get_client()
        r = await client.get("/api/schema", headers=_read_headers())
        r.raise_for_status()
        data = r.json()
        # Response is a JSON Schema with top-level definitions/properties
        definitions: dict[str, Any] = data.get("$defs", data.get("definitions", {}))
        return list(definitions.keys())

    @mcp.tool()
    async def get_block_schema(block_type: str) -> dict[str, Any]:
        """
        Return the JSON Schema for a specific block type, including field labels,
        required/optional status, and any constraints.

        :param block_type: The block type name (from list_block_types).
        """
        client = _get_client()
        r = await client.get(f"/api/schema/{block_type}", headers=_read_headers())
        if r.status_code == 404:
            return {"error": f"Block type {block_type!r} not found"}
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Document read tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_documents(
        doc_type: str | None = None,
        published: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List documents, optionally filtered by type and publish status.

        Returns a dict with keys:
        - ``documents``: list of document objects
        - ``total``: total count matching the query (before limit/offset)
        - ``filters_applied``: echo of any filters that were applied

        :param doc_type: Filter to one block type, e.g. ``"blog_post"``.
            Omit to return documents of all types.
        :param published: ``True`` for only published documents, ``False`` for
            only drafts, ``None`` (default) for all.
        :param limit: Max number of documents to return (default 20).
        :param offset: Number of documents to skip for pagination (default 0).
        """
        client = _get_client()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if doc_type is not None:
            params["type"] = doc_type
        if published is not None:
            params["published"] = str(published).lower()
        r = await client.get("/api/documents", params=params, headers=_read_headers())
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def get_document(doc_id: str) -> dict[str, Any]:
        """
        Return a single document by its nanoid.

        :param doc_id: The document's nanoid (e.g. ``"V1StGXR8_Z5jdHi6B-myT"``).
            You can obtain IDs from list_documents.
        """
        client = _get_client()
        r = await client.get(f"/api/documents/{doc_id}", headers=_read_headers())
        if r.status_code == 404:
            return {"error": f"Document {doc_id!r} not found"}
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Document write tools
    # ------------------------------------------------------------------

    @mcp.tool()
    async def create_document(
        doc_type: str,
        body: dict[str, Any],
        slug: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new document.  The document is created in draft state; call
        publish_document to make it publicly visible.

        For append_only block types, the document is automatically published
        immediately — no second call is needed.

        :param doc_type: Block type name (from list_block_types).
        :param body: Document body.  Must match the block's schema
            (use get_block_schema to see required fields).
        :param slug: Optional URL slug for this document.
        :param meta: Optional metadata dict (arbitrary key/value pairs).
        """
        client = _get_client()
        payload: dict[str, Any] = {
            "doc_type": doc_type,
            "body": body,
            "slug": slug,
        }
        if meta:
            payload["meta"] = meta
        r = await client.post("/api/documents", json=payload)
        if r.status_code == 422:
            return {"error": "Validation failed", "detail": r.json()}
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def update_document(
        doc_id: str,
        body: dict[str, Any] | None = None,
        slug: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Partially update an existing document (PATCH semantics — only the fields
        you provide are changed; omitted fields are left as-is).

        Returns 405 for append_only block types (those documents cannot be modified
        after creation).

        :param doc_id: The document's nanoid.
        :param body: Partial body dict to merge into the existing body.
        :param slug: New slug value, if changing.
        :param meta: Partial meta dict to merge into the existing meta.
        """
        client = _get_client()
        payload: dict[str, Any] = {}
        if body is not None:
            payload["body"] = body
        if slug is not None:
            payload["slug"] = slug
        if meta is not None:
            payload["meta"] = meta
        r = await client.patch(f"/api/documents/{doc_id}", json=payload)
        if r.status_code == 404:
            return {"error": f"Document {doc_id!r} not found"}
        if r.status_code == 405:
            return {"error": r.json().get("error", "Method not allowed")}
        if r.status_code == 422:
            return {"error": "Validation failed", "detail": r.json()}
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def delete_document(doc_id: str) -> dict[str, Any]:
        """
        Delete a document permanently.

        Returns 409 if other documents reference this one with on_delete="block".
        Returns 405 for append_only block types.

        :param doc_id: The document's nanoid.
        """
        client = _get_client()
        r = await client.delete(f"/api/documents/{doc_id}")
        if r.status_code == 404:
            return {"error": f"Document {doc_id!r} not found"}
        if r.status_code == 405:
            return {"error": r.json().get("error", "Method not allowed")}
        if r.status_code == 409:
            return {"error": r.json().get("error", "Conflict — referenced document")}
        r.raise_for_status()
        return {"deleted": True, "doc_id": doc_id}

    @mcp.tool()
    async def publish_document(doc_id: str) -> dict[str, Any]:
        """
        Publish a document, making it publicly visible.

        For singleton block types, publishing a new version automatically archives
        the previously active version — only one version is "active" at a time.

        :param doc_id: The document's nanoid.
        """
        client = _get_client()
        r = await client.post(f"/api/documents/{doc_id}/publish")
        if r.status_code == 404:
            return {"error": f"Document {doc_id!r} not found"}
        r.raise_for_status()
        return r.json()

    @mcp.tool()
    async def unpublish_document(doc_id: str) -> dict[str, Any]:
        """
        Unpublish a document, reverting it to draft state.

        :param doc_id: The document's nanoid.
        """
        client = _get_client()
        r = await client.post(f"/api/documents/{doc_id}/unpublish")
        if r.status_code == 404:
            return {"error": f"Document {doc_id!r} not found"}
        r.raise_for_status()
        return r.json()

    return mcp
