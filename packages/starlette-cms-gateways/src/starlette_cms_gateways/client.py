"""
CMSClient — thin httpx wrapper for the starlette-cms HTTP API.

Handles authentication, deduplication lookups, and upserts.
All operations are async.

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

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Literal

import httpx
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from starlette_cms_gateways.base import GatewayItem

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


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

    async def create_changeset(self, title: str) -> str:
        """Create an open changeset via ``POST /api/changesets`` and return its id."""
        http = self._get_http()
        resp = await http.post(
            f"{self.base_url}/api/changesets",
            json={"title": title},
            headers=self._auth_headers(),
        )
        if resp.status_code not in (200, 201):
            raise CMSError(resp.status_code, resp.text)
        return resp.json()["id"]

    def _changeset_headers(self, changeset_id: str | None) -> dict[str, str]:
        """Auth headers plus the active-changeset header when grouping a run."""
        headers = self._auth_headers()
        if changeset_id is not None:
            headers["X-Active-Changeset-Id"] = changeset_id
        return headers

    async def create_document(
        self,
        *,
        doc_type: str,
        slug: str,
        body: dict[str, Any],
        import_ref: str | None = None,
        meta: dict[str, Any] | None = None,
        changeset_id: str | None = None,
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
            headers=self._changeset_headers(changeset_id),
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
        changeset_id: str | None = None,
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
            headers=self._changeset_headers(changeset_id),
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

    async def publish_changeset(self, changeset_id: str) -> dict[str, Any]:
        """Publish a changeset via ``POST /api/changesets/{id}/publish``."""
        http = self._get_http()
        resp = await http.post(
            f"{self.base_url}/api/changesets/{changeset_id}/publish",
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json()

    async def discard_draft(self, doc_id: str) -> dict[str, Any]:
        """Throw away a document's pending draft via ``POST /api/documents/{id}/discard-draft``."""
        http = self._get_http()
        resp = await http.post(
            f"{self.base_url}/api/documents/{doc_id}/discard-draft",
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
        auto_publish: bool = False,
        changeset_provider: Callable[[], Awaitable[str]] | None = None,
        owned_fields: Iterable[str] | None = None,
        publish_with_changeset: bool = False,
    ) -> Literal["created", "updated", "skipped", "deferred"]:
        """
        Create, update, skip or defer a document based on ``import_ref``
        deduplication.

        Decision logic:

        1. Look up an existing document by ``(block_type, import_ref)``.
        2. None found → create with the *whole* body.  Return ``"created"``.
        3. Found and the hash of the *owned* fields matches the stored one →
           write nothing.  Return ``"skipped"``.
        4. Found, hash differs, but a human holds a pending draft on it or
           deliberately unpublished it → write nothing.  Return ``"deferred"``.
           Patching would merge into their draft, and publishing would push their
           work-in-progress live.
        5. Found, hash differs → PATCH **only the owned fields**, so anything a
           human added or edited elsewhere survives, then publish if asked.
           Return ``"updated"``.

        ``owned_fields=None`` treats the whole body as owned.  The hash is kept
        in ``meta.content_hash`` so it survives restarts.  It is a hash of what
        the gateway *sent*, never of what the CMS stored back (the CMS validates
        and rewrites bodies).

        ``changeset_provider`` is an optional async callable resolved only when
        this call actually writes. It returns the id of the changeset to group
        the write into — the caller uses it to lazily open one changeset per
        sync run without creating one for an all-skip run.

        ``publish_with_changeset`` says the caller will publish that changeset
        itself, so the document is not also published here.
        """
        with tracer.start_as_current_span("gateways.client.upsert") as span:
            span.set_attribute("doc_type", block_type)
            span.set_attribute("import_ref", item.import_ref)
            try:
                existing = await self.find_by_import_ref(block_type, item.import_ref)
                new_hash = item.content_hash(owned_fields)

                if existing is None:
                    meta: dict[str, Any] = {"content_hash": new_hash}
                    if item.title:
                        meta["title"] = item.title
                    cs_id = await changeset_provider() if changeset_provider is not None else None
                    doc = await self.create_document(
                        doc_type=block_type,
                        slug=item.slug,
                        body=item.body,
                        import_ref=item.import_ref,
                        meta=meta,
                        changeset_id=cs_id,
                    )
                    if auto_publish and not publish_with_changeset:
                        await self.publish_document(doc["id"])
                    span.set_attribute("action", "created")
                    return "created"

                existing_meta = existing.get("meta") or {}
                if isinstance(existing_meta, str):
                    import json as _json

                    try:
                        existing_meta = _json.loads(existing_meta)
                    except Exception:
                        logger.warning(
                            "starlette_cms_gateways.client.meta_parse_failed",
                            import_ref=item.import_ref,
                        )
                        existing_meta = {}

                published = bool(existing.get("published"))
                never_published = not published and not existing.get("published_at")

                if existing_meta.get("content_hash", "") == new_hash:
                    span.set_attribute("action", "skipped")
                    return "skipped"

                if existing.get("has_draft") or (not published and not never_published):
                    logger.info(
                        "starlette_cms_gateways.client.deferred",
                        import_ref=item.import_ref,
                        pending_draft=bool(existing.get("has_draft")),
                    )
                    span.set_attribute("action", "deferred")
                    return "deferred"

                cs_id = await changeset_provider() if changeset_provider is not None else None
                await self.update_document(
                    existing["id"],
                    body=item.owned_body(owned_fields),
                    meta={**existing_meta, "content_hash": new_hash},
                    changeset_id=cs_id,
                )
                if auto_publish and not publish_with_changeset:
                    await self.publish_document(existing["id"])
                span.set_attribute("action", "updated")
                return "updated"
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                raise

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
