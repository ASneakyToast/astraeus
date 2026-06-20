"""
CMSClient — thin httpx wrapper for the starlette-cms HTTP API.

Handles authentication, deduplication lookups, upserts, and sync state
persistence.  All operations are async.

Usage::

    from starlette_cms_gateways.client import CMSClient

    client = CMSClient(
        base_url="https://cms.example.com",
        api_key="secret",
    )

    action = await client.upsert(
        item=GatewayItem(
            import_ref="spotify:liked:abc123",
            slug="spotify-liked-abc123",
            body={"track_name": "Bohemian Rhapsody"},
        ),
        block_type="spotify_liked_song",
        auto_publish=True,
    )
    # action is "created", "updated", or "skipped"
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import httpx

from starlette_cms_gateways.base import GatewayItem, SyncResult


class CMSError(Exception):
    """Raised when the CMS API returns an unexpected response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        super().__init__(f"CMS API error {status_code}: {detail}")


class CMSClient:
    """
    Thin httpx wrapper for the starlette-cms document API.

    :param base_url: Base URL of the starlette-cms instance, without trailing
        slash (e.g. ``https://cms.example.com`` or ``http://localhost:8000/cms``).
    :param api_key: Optional API key sent as ``Authorization: Bearer <key>``
        on all mutating requests.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
        _http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = _http_client

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout)
        return self._http

    async def close(self) -> None:
        """Close the underlying httpx client (if owned by this instance)."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Auth header
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def find_by_import_ref(
        self, doc_type: str, import_ref: str
    ) -> dict[str, Any] | None:
        """
        Look up an existing document by ``(doc_type, import_ref)``.

        Returns the document dict if found, ``None`` otherwise.
        """
        http = self._get_http()
        resp = await http.get(
            f"{self.base_url}/api/documents",
            params={"type": doc_type, "import_ref": import_ref, "limit": 1},
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        data = resp.json()
        docs = data.get("documents", [])
        return docs[0] if docs else None

    async def create_document(
        self,
        *,
        doc_type: str,
        slug: str,
        body: dict[str, Any],
        import_ref: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new document via ``POST /api/documents``.

        :raises CMSError: on HTTP error (including 409 duplicate import_ref).
        """
        http = self._get_http()
        payload: dict[str, Any] = {
            "doc_type": doc_type,
            "slug": slug,
            "body": body,
        }
        if import_ref is not None:
            payload["import_ref"] = import_ref
        if meta:
            payload["meta"] = meta

        resp = await http.post(
            f"{self.base_url}/api/documents",
            json=payload,
            headers=self._auth_headers(),
        )
        if resp.status_code not in (200, 201):
            raise CMSError(resp.status_code, resp.text)
        return resp.json()

    async def update_document(
        self,
        doc_id: str,
        *,
        body: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Update an existing document via ``PATCH /api/documents/{id}``.
        """
        http = self._get_http()
        payload: dict[str, Any] = {"body": body}
        if meta:
            payload["meta"] = meta

        resp = await http.patch(
            f"{self.base_url}/api/documents/{doc_id}",
            json=payload,
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json()

    async def publish_document(self, doc_id: str) -> dict[str, Any]:
        """Publish a document via ``POST /api/documents/{id}/publish``."""
        http = self._get_http()
        resp = await http.post(
            f"{self.base_url}/api/documents/{doc_id}/publish",
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json()

    async def upsert(
        self,
        *,
        item: GatewayItem,
        block_type: str,
        auto_publish: bool = True,
    ) -> Literal["created", "updated", "skipped"]:
        """
        Create, update, or skip a document based on ``import_ref`` deduplication.

        Decision logic:

        1. Look up an existing document by ``(block_type, import_ref)``.
        2. If none found → create and optionally publish.  Return ``"created"``.
        3. If found and body hash unchanged → do nothing.  Return ``"skipped"``.
        4. If found and body hash changed → update body.  Return ``"updated"``.

        The content hash is stored in the document's ``meta.content_hash`` field
        so it survives across process restarts without re-fetching the full body.
        """
        existing = await self.find_by_import_ref(block_type, item.import_ref)

        if existing is None:
            # Create new document
            meta: dict[str, Any] = {"content_hash": item.content_hash()}
            if item.title:
                meta["title"] = item.title
            doc = await self.create_document(
                doc_type=block_type,
                slug=item.slug,
                body=item.body,
                import_ref=item.import_ref,
                meta=meta,
            )
            if auto_publish:
                await self.publish_document(doc["id"])
            return "created"

        # Compare content hash to decide whether to update
        existing_meta = existing.get("meta") or {}
        if isinstance(existing_meta, str):
            import json as _json

            try:
                existing_meta = _json.loads(existing_meta)
            except Exception:
                existing_meta = {}

        stored_hash = existing_meta.get("content_hash", "")
        if stored_hash == item.content_hash():
            return "skipped"

        # Update body and refresh content hash
        new_meta = {**existing_meta, "content_hash": item.content_hash()}
        if item.title:
            new_meta["title"] = item.title
        await self.update_document(
            existing["id"],
            body=item.body,
            meta=new_meta,
        )
        if auto_publish and not existing.get("published"):
            await self.publish_document(existing["id"])
        return "updated"

    # ------------------------------------------------------------------
    # Sync state helpers (GatewaySyncState singleton)
    # ------------------------------------------------------------------

    async def get_last_synced(self, service_name: str) -> datetime | None:
        """
        Return the last successful sync time for ``service_name``, or ``None``
        if no sync state exists.

        Reads the ``gateway_sync_state`` singleton and extracts the
        ``last_synced`` timestamp for this service.
        """
        http = self._get_http()
        resp = await http.get(
            f"{self.base_url}/api/documents/singleton/gateway_sync_state",
            headers=self._auth_headers(),
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)

        data = resp.json()
        body = data.get("body") or {}
        services = body.get("services") or {}
        svc = services.get(service_name) or {}
        ts_str = svc.get("last_synced")
        if ts_str:
            try:
                return datetime.fromisoformat(ts_str)
            except ValueError:
                return None
        return None

    async def save_sync_state(
        self,
        *,
        service_name: str,
        body: dict[str, Any],
    ) -> None:
        """
        Publish an updated ``gateway_sync_state`` singleton to the CMS.

        Reads the current active singleton (if any), merges the new service
        entry, and publishes the updated version via
        ``POST /api/documents/singleton/gateway_sync_state``.
        """
        http = self._get_http()

        # Read current state so we can merge service entries
        current_services: dict[str, Any] = {}
        resp = await http.get(
            f"{self.base_url}/api/documents/singleton/gateway_sync_state",
            headers=self._auth_headers(),
        )
        if resp.status_code == 200:
            current_body = resp.json().get("body") or {}
            current_services = current_body.get("services") or {}

        # Merge in the new service body (body is already the per-service dict)
        current_services[service_name] = body.get("services", {}).get(service_name, body)

        new_body: dict[str, Any] = {"services": current_services}

        post_resp = await http.post(
            f"{self.base_url}/api/documents/singleton/gateway_sync_state",
            json={"body": new_body},
            headers=self._auth_headers(),
        )
        if post_resp.status_code not in (200, 201):
            # Sync state persistence failure is non-fatal — log but don't raise
            pass

    async def list_documents(
        self,
        *,
        doc_type: str | None = None,
        import_ref: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List documents with optional type and import_ref filters.

        Returns the raw API response dict (``{"documents": [...], "total": N}``).
        """
        http = self._get_http()
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if doc_type:
            params["type"] = doc_type
        if import_ref is not None:
            params["import_ref"] = import_ref

        resp = await http.get(
            f"{self.base_url}/api/documents",
            params=params,
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json()

    async def get_gateway_status(self) -> dict[str, Any]:
        """
        Return the current ``gateway_sync_state`` singleton body, or ``{}`` if
        no sync state has been persisted yet.
        """
        http = self._get_http()
        resp = await http.get(
            f"{self.base_url}/api/documents/singleton/gateway_sync_state",
            headers=self._auth_headers(),
        )
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json().get("body") or {}
