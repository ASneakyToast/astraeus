"""Changeset endpoints — /api/changesets

Changesets group multiple documents for atomic publish.  A single webhook
event (``changeset.published``) fires after all documents in the changeset
are published, rather than one event per document.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from nanoid import generate
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from starlette_cms.auth import require_auth
from starlette_cms.tables import CMSChangeset, CMSChangesetDocument, CMSDocument, CMSWebhook

if TYPE_CHECKING:
    from starlette_cms.app import CMS

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _changeset_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw CMSChangeset row to a JSON-serialisable dict."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


async def _get_changeset_documents(changeset_id: str) -> list[dict[str, Any]]:
    """Return minimal document info for all docs in a changeset."""
    join_rows = (
        await CMSChangesetDocument.select()
        .where(CMSChangesetDocument.changeset_id == changeset_id)
        .run()
    )
    if not join_rows:
        return []

    doc_ids = [r["document_id"] for r in join_rows]
    doc_rows = await CMSDocument.select(
        CMSDocument.id,
        CMSDocument.doc_type,
        CMSDocument.slug,
    ).where(CMSDocument.id.is_in(doc_ids)).run()

    # Build a quick lookup for has_draft (gracefully absent if column not yet added)
    result = []
    for r in doc_rows:
        result.append(
            {
                "id": r["id"],
                "doc_type": r["doc_type"],
                "slug": r.get("slug", ""),
                "has_draft": False,  # will be True once Phase 1A is merged
            }
        )
    return result


async def _build_full_changeset(row: dict[str, Any]) -> dict[str, Any]:
    """Return a full changeset dict including document list."""
    d = _changeset_to_dict(row)
    d["documents"] = await _get_changeset_documents(row["id"])
    return d


async def _fire_changeset_webhook(
    cms: "CMS",
    event: str,
    changeset_id: str,
    title: str,
    doc_ids: list[str],
    now: datetime,
) -> None:
    """
    Deliver *event* to all matching active webhooks.

    Piccolo doesn't support JSON-contains queries on SQLite, so we filter in Python.
    """
    import starlette_cms.api.webhooks as _webhooks_module

    rows = await CMSWebhook.select().where(CMSWebhook.active == True).run()  # noqa: E712

    payload: dict[str, Any] = {
        "event": event,
        "changeset_id": changeset_id,
        "title": title,
        "document_ids": doc_ids,
        "document_count": len(doc_ids),
        "timestamp": now.isoformat(),
    }

    loop = asyncio.get_running_loop()
    for row in rows:
        raw_events = row.get("events", "[]")
        if isinstance(raw_events, str):
            try:
                events_list = json.loads(raw_events)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "starlette_cms.changesets.webhook_events_parse_failed",
                    webhook_id=row.get("id"),
                )
                events_list = []
        else:
            events_list = raw_events if isinstance(raw_events, list) else []

        if event in events_list:
            task = loop.create_task(_webhooks_module._deliver(row["url"], payload))
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )


async def _publish_changeset_logic(changeset_id: str, cms: "CMS") -> dict[str, Any] | None:
    """
    Core publish logic — shared between the HTTP endpoint and the scheduler.

    Returns the updated changeset dict on success, or None if not found.
    Raises ValueError with a message if the changeset is in the wrong state.
    """
    rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
    if not rows:
        return None

    changeset = rows[0]
    if changeset["status"] not in ("open", "scheduled"):
        raise ValueError(f"Changeset status is {changeset['status']!r}; must be 'open' or 'scheduled'")

    now = datetime.now(UTC)

    # Collect document IDs
    join_rows = (
        await CMSChangesetDocument.select()
        .where(CMSChangesetDocument.changeset_id == changeset_id)
        .run()
    )
    doc_ids = [r["document_id"] for r in join_rows]

    # Publish each document, promoting draft_body if present
    for doc_id in doc_ids:
        doc_rows = await CMSDocument.select().where(CMSDocument.id == doc_id).run()
        if not doc_rows:
            logger.warning(
                "starlette_cms.changesets.missing_document",
                changeset_id=changeset_id,
                document_id=doc_id,
            )
            continue

        doc_row = doc_rows[0]

        # Build update fields
        update_fields: dict[Any, Any] = {
            CMSDocument.published: True,
            CMSDocument.published_at: now,
            CMSDocument.updated_at: now,
        }

        # Promote draft_body → body if present (Phase 1A compat)
        draft_body_raw = doc_row.get("draft_body")
        if draft_body_raw is not None:
            # Parse if stored as string
            if isinstance(draft_body_raw, str):
                try:
                    draft_body_parsed = json.loads(draft_body_raw)
                except Exception:
                    logger.warning(
                        "starlette_cms.changesets.draft_body_parse_failed",
                        doc_id=doc_id,
                    )
                    draft_body_parsed = None
            else:
                draft_body_parsed = draft_body_raw

            if draft_body_parsed is not None:
                update_fields[CMSDocument.body] = json.dumps(draft_body_parsed)
                # Clear draft fields — use string key for forward compat with
                # columns that may not exist yet in the current schema
                try:
                    update_fields[CMSDocument.draft_body] = None  # type: ignore[attr-defined]
                    update_fields[CMSDocument.draft_version] = 0  # type: ignore[attr-defined]
                except AttributeError:
                    pass  # draft columns not yet in schema — skip

        await CMSDocument.update(update_fields).where(CMSDocument.id == doc_id).run()

    # Mark changeset published
    await (
        CMSChangeset.update(
            {
                CMSChangeset.status: "published",
                CMSChangeset.published_at: now,
            }
        )
        .where(CMSChangeset.id == changeset_id)
        .run()
    )

    # Fire webhook (fire-and-forget)
    loop = asyncio.get_running_loop()
    loop.create_task(
        _fire_changeset_webhook(
            cms,
            "changeset.published",
            changeset_id,
            changeset["title"],
            doc_ids,
            now,
        )
    )

    # Return updated changeset
    updated_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
    return await _build_full_changeset(updated_rows[0])


# ---------------------------------------------------------------------------
# Route factory
# ---------------------------------------------------------------------------


def make_changeset_routes(cms: "CMS") -> list[Route]:
    """Build and return all changeset routes, closed over ``cms``."""

    async def create_changeset(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        try:
            data = await request.json()
        except Exception:
            data = {}

        title = data.get("title", "") if isinstance(data, dict) else ""
        changeset_id = generate(size=21)
        now = datetime.now(UTC)

        await CMSChangeset.insert(
            CMSChangeset(
                id=changeset_id,
                title=title,
                status="open",
                created_at=now,
                publish_at=None,
                published_at=None,
            )
        ).run()

        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        result = await _build_full_changeset(rows[0])
        return JSONResponse(result, status_code=201)

    async def list_changesets(request: Request) -> JSONResponse:
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        status_filter = request.query_params.get("status")

        query = CMSChangeset.select().order_by(CMSChangeset.created_at, ascending=False)
        if status_filter:
            query = query.where(CMSChangeset.status == status_filter)

        rows = await query.run()

        result = []
        for row in rows:
            d = _changeset_to_dict(row)
            # Attach document_count
            count = await (
                CMSChangesetDocument.count()
                .where(CMSChangesetDocument.changeset_id == row["id"])
                .run()
            )
            d["document_count"] = count
            result.append(d)

        return JSONResponse({"changesets": result})

    async def get_changeset(request: Request) -> JSONResponse:
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        changeset_id = request.path_params["id"]
        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        result = await _build_full_changeset(rows[0])
        return JSONResponse(result)

    async def add_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]
        doc_id = request.path_params["doc_id"]

        cs_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not cs_rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        changeset = cs_rows[0]
        if changeset["status"] != "open":
            return JSONResponse(
                {"error": f"Cannot add documents to a changeset with status {changeset['status']!r}"},
                status_code=400,
            )

        doc_rows = await CMSDocument.select(CMSDocument.id).where(CMSDocument.id == doc_id).run()
        if not doc_rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        # 409 if already in changeset
        existing = (
            await CMSChangesetDocument.select()
            .where(
                CMSChangesetDocument.changeset_id == changeset_id,
                CMSChangesetDocument.document_id == doc_id,
            )
            .run()
        )
        if existing:
            return JSONResponse(
                {"error": "Document is already in this changeset"},
                status_code=409,
            )

        now = datetime.now(UTC)
        await CMSChangesetDocument.insert(
            CMSChangesetDocument(
                changeset_id=changeset_id,
                document_id=doc_id,
                added_at=now,
            )
        ).run()

        updated_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        result = await _build_full_changeset(updated_rows[0])
        return JSONResponse(result)

    async def remove_document(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]
        doc_id = request.path_params["doc_id"]

        cs_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not cs_rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        doc_rows = await CMSDocument.select(CMSDocument.id).where(CMSDocument.id == doc_id).run()
        if not doc_rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        join_rows = (
            await CMSChangesetDocument.select()
            .where(
                CMSChangesetDocument.changeset_id == changeset_id,
                CMSChangesetDocument.document_id == doc_id,
            )
            .run()
        )
        if not join_rows:
            return JSONResponse(
                {"error": "Document is not in this changeset"},
                status_code=404,
            )

        await (
            CMSChangesetDocument.delete()
            .where(
                CMSChangesetDocument.changeset_id == changeset_id,
                CMSChangesetDocument.document_id == doc_id,
            )
            .run()
        )

        updated_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        result = await _build_full_changeset(updated_rows[0])
        return JSONResponse(result)

    async def delete_changeset(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]
        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        changeset = rows[0]
        if changeset["status"] == "published":
            return JSONResponse(
                {"error": "Cannot delete a published changeset"},
                status_code=400,
            )

        # Delete join rows first, then changeset
        await (
            CMSChangesetDocument.delete()
            .where(CMSChangesetDocument.changeset_id == changeset_id)
            .run()
        )
        await CMSChangeset.delete().where(CMSChangeset.id == changeset_id).run()

        return JSONResponse({"deleted": True})

    async def publish_changeset(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]

        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        changeset = rows[0]
        if changeset["status"] not in ("open", "scheduled"):
            return JSONResponse(
                {
                    "error": (
                        f"Changeset status is {changeset['status']!r}; "
                        "must be 'open' or 'scheduled' to publish"
                    )
                },
                status_code=400,
            )

        try:
            result = await _publish_changeset_logic(changeset_id, cms)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        if result is None:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        return JSONResponse(result)

    async def schedule_changeset(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]
        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        publish_at_str = data.get("publish_at")
        if not publish_at_str:
            return JSONResponse({"error": "publish_at is required"}, status_code=422)

        try:
            publish_at = datetime.fromisoformat(publish_at_str)
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": "publish_at must be a valid ISO 8601 datetime string"},
                status_code=400,
            )

        # Ensure timezone-aware
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        if publish_at <= now:
            return JSONResponse(
                {"error": "publish_at must be in the future"},
                status_code=400,
            )

        await (
            CMSChangeset.update(
                {
                    CMSChangeset.status: "scheduled",
                    CMSChangeset.publish_at: publish_at,
                }
            )
            .where(CMSChangeset.id == changeset_id)
            .run()
        )

        updated_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        result = await _build_full_changeset(updated_rows[0])
        return JSONResponse(result)

    async def unschedule_changeset(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        changeset_id = request.path_params["id"]
        rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        if not rows:
            return JSONResponse({"error": "Changeset not found"}, status_code=404)

        changeset = rows[0]
        if changeset["status"] != "scheduled":
            return JSONResponse(
                {"error": f"Changeset is not scheduled (status: {changeset['status']!r})"},
                status_code=400,
            )

        await (
            CMSChangeset.update(
                {
                    CMSChangeset.status: "open",
                    CMSChangeset.publish_at: None,
                }
            )
            .where(CMSChangeset.id == changeset_id)
            .run()
        )

        updated_rows = await CMSChangeset.select().where(CMSChangeset.id == changeset_id).run()
        result = await _build_full_changeset(updated_rows[0])
        return JSONResponse(result)

    return [
        Route("/api/changesets", endpoint=create_changeset, methods=["POST"]),
        Route("/api/changesets", endpoint=list_changesets, methods=["GET"]),
        Route("/api/changesets/{id}", endpoint=get_changeset, methods=["GET"]),
        Route("/api/changesets/{id}", endpoint=delete_changeset, methods=["DELETE"]),
        Route(
            "/api/changesets/{id}/documents/{doc_id}",
            endpoint=add_document,
            methods=["POST"],
        ),
        Route(
            "/api/changesets/{id}/documents/{doc_id}",
            endpoint=remove_document,
            methods=["DELETE"],
        ),
        Route("/api/changesets/{id}/publish", endpoint=publish_changeset, methods=["POST"]),
        Route("/api/changesets/{id}/schedule", endpoint=schedule_changeset, methods=["POST"]),
        Route(
            "/api/changesets/{id}/unschedule",
            endpoint=unschedule_changeset,
            methods=["POST"],
        ),
    ]
