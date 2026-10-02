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

import json
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Literal

import httpx
import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

from starlette_cms_gateways.base import GatewayItem
from starlette_cms_gateways.drafts import draft_verdict

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
        link_changeset: bool = True,
    ) -> dict[str, Any]:
        """
        Update an existing document via ``PATCH /api/documents/{id}``.

        The CMS links every PATCH into an open changeset, creating a date-titled
        one when none is given. Pass ``link_changeset=False`` when the caller
        publishes the document itself straight away: it sends ``X-Skip-Changeset``
        so no changeset is opened that nothing would ever publish or close.
        ``changeset_id``, when given, always wins.
        """
        http = self._get_http()
        payload: dict[str, Any] = {"body": body}
        if meta:
            payload["meta"] = meta

        headers = self._changeset_headers(changeset_id)
        if changeset_id is None and not link_changeset:
            headers["X-Skip-Changeset"] = "1"
        resp = await http.patch(
            f"{self.base_url}/api/documents/{doc_id}",
            json=payload,
            headers=headers,
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

    async def get_draft_body(self, doc_id: str) -> dict[str, Any]:
        """The document's pending draft body (the live body when there is no draft)."""
        http = self._get_http()
        resp = await http.get(
            f"{self.base_url}/api/documents/{doc_id}",
            params={"draft": "true"},
            headers=self._auth_headers(),
        )
        if resp.status_code != 200:
            raise CMSError(resp.status_code, resp.text)
        return resp.json().get("body") or {}

    async def gateway_request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Call the CMS gateway API: ``{method} /api/gateways/{path}``.

        This is how a worker outside the CMS process reads and writes the sync
        cursor, the retry list and the job history, which live in the CMS's
        database. Returns the JSON body (``{}`` when there is none).
        """
        http = self._get_http()
        resp = await http.request(
            method,
            f"{self.base_url}/api/gateways/{path}",
            json=payload,
            headers=self._auth_headers(),
        )
        if resp.status_code not in (200, 201):
            raise CMSError(resp.status_code, resp.text)
        return resp.json() if resp.content else {}

    async def _draft_is_gateways(
        self, existing: dict[str, Any], owned_fields: Iterable[str] | None
    ) -> bool:
        """
        True when the pending draft on *existing* is the gateway's own leftover.

        A person's draft — one that changes anything but owned fields, or a staged
        deletion or publish-state change — is not. See :mod:`starlette_cms_gateways.drafts`.
        """
        if existing.get("draft_deleted") or existing.get("draft_published") is not None:
            return False
        draft = await self.get_draft_body(existing["id"])
        verdict, _ = draft_verdict(existing.get("body") or {}, draft, owned_fields)
        return verdict != "human-edits"

    async def upsert(
        self,
        *,
        item: GatewayItem,
        block_type: str,
        auto_publish: bool = False,
        changeset_provider: Callable[[], Awaitable[str]] | None = None,
        owned_fields: Iterable[str] | None = None,
    ) -> Literal["created", "updated", "skipped", "deferred"]:
        """
        Create, update, skip or defer a document based on ``import_ref``
        deduplication.

        Decision logic:

        1. Look up an existing document by ``(block_type, import_ref)``.
        2. None found → create with the *whole* body, and publish it if
           *auto_publish*.  Return ``"created"``.
        3. Found with a pending **draft**.  Checked *before* the hash, because a
           matching hash can hide a draft whose publish failed.

           * A person's draft (it changes more than owned fields, or a person
             unpublished the document) → write nothing.  ``"deferred"`` if the
             source changed, ``"skipped"`` if it did not (nothing to wait for).
           * The gateway's own draft → fall through to step 5 and finish it: a
             PATCH whose publish failed is re-PATCHed and published.  On a
             review gateway (*auto_publish* False) a draft that is already
             current is ``"skipped"``; a stale one is re-PATCHed, which is what
             lets a never-published draft take a second and third update.
        4. Found, no draft, and the hash of the *owned* fields matches → write
           nothing.  ``"skipped"``.  The exception: an auto-publish gateway whose
           document was created but never published (the publish failed) →
           publish it.  ``"updated"``.  A document a person unpublished stays
           unpublished; if the source changed meanwhile → ``"deferred"``.
        5. Otherwise PATCH **only the owned fields**, so anything a person added
           or edited elsewhere survives, then publish **that document** right
           away if *auto_publish*.  ``"updated"``.

        ``owned_fields=None`` treats the whole body as owned, and then any draft
        is a person's (nothing can be told apart).  The hash is kept in
        ``meta.content_hash`` so it survives restarts.  It is a hash of what the
        gateway *sent*, never of what the CMS stored back (the CMS validates and
        rewrites bodies).

        ``changeset_provider`` is an optional async callable resolved only when
        this call actually writes. It returns the id of the changeset to group
        the write into: the review batch of a gateway that does not publish.
        Without one the PATCH opts out of the CMS's auto-changeset
        (``X-Skip-Changeset``), since publishing here leaves nothing to batch.
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
                    if auto_publish:
                        await self.publish_document(doc["id"])
                    span.set_attribute("action", "created")
                    return "created"

                existing_meta = existing.get("meta") or {}
                if isinstance(existing_meta, str):
                    try:
                        existing_meta = json.loads(existing_meta)
                    except Exception:
                        logger.warning(
                            "starlette_cms_gateways.client.meta_parse_failed",
                            import_ref=item.import_ref,
                        )
                        existing_meta = {}

                published = bool(existing.get("published"))
                ever_published = published or bool(existing.get("published_at"))
                unpublished_by_person = ever_published and not published
                same = existing_meta.get("content_hash", "") == new_hash

                def deferred(reason: str) -> Literal["deferred"]:
                    logger.info(
                        "starlette_cms_gateways.client.deferred",
                        import_ref=item.import_ref,
                        reason=reason,
                    )
                    span.set_attribute("action", "deferred")
                    return "deferred"

                if existing.get("has_draft"):
                    mine = not unpublished_by_person and await self._draft_is_gateways(
                        existing, owned_fields
                    )
                    if not mine:
                        if same:  # nothing to write, so nothing to wait for either
                            span.set_attribute("action", "skipped")
                            return "skipped"
                        return deferred("a person's draft or unpublish is in the way")
                    if same and not auto_publish:
                        span.set_attribute("action", "skipped")
                        return "skipped"  # review gateway: the draft already says this
                elif same:
                    if auto_publish and not ever_published:
                        # Created, but the publish never happened. Nothing to write.
                        await self.publish_document(existing["id"])
                        span.set_attribute("action", "updated")
                        return "updated"
                    span.set_attribute("action", "skipped")
                    return "skipped"
                elif unpublished_by_person:
                    return deferred("unpublished by a person")

                cs_id = await changeset_provider() if changeset_provider is not None else None
                await self.update_document(
                    existing["id"],
                    body=item.owned_body(owned_fields),
                    meta={**existing_meta, "content_hash": new_hash},
                    changeset_id=cs_id,
                    link_changeset=False,
                )
                if auto_publish:
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
