"""Webhook registration and delivery — /api/webhooks"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
from nanoid import generate
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from starlette_cms.auth import require_auth
from starlette_cms.tables import CMSWebhook

if TYPE_CHECKING:
    from starlette_cms.app import CMS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fire-and-forget delivery
# ---------------------------------------------------------------------------


async def _deliver(url: str, payload: dict[str, Any]) -> None:
    """POST *payload* to *url*; swallow all errors and log failures."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Webhook delivery failed to %s: %s", url, exc)


async def fire_event(
    cms: CMS,  # noqa: ARG001 — kept for future use (per-cms filtering)
    event: str,
    doc_id: str,
    doc_type: str,
    slug: str,
) -> None:
    """
    Dispatch *event* to all matching active webhooks as fire-and-forget tasks.

    Piccolo doesn't support native JSON-contains queries on SQLite, so we
    fetch all active webhooks and filter in Python.

    :param cms: The CMS instance (reserved for future per-instance filtering).
    :param event: Event name, e.g. ``"document.published"``.
    :param doc_id: The document's nanoid.
    :param doc_type: The registered document type name.
    :param slug: The document's slug.
    """
    rows = await CMSWebhook.select().where(CMSWebhook.active == True).run()  # noqa: E712

    payload: dict[str, Any] = {
        "event": event,
        "document_id": doc_id,
        "document_type": doc_type,
        "slug": slug,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    loop = asyncio.get_running_loop()
    for row in rows:
        raw_events = row.get("events", "[]")
        if isinstance(raw_events, str):
            try:
                events_list = json.loads(raw_events)
            except (json.JSONDecodeError, TypeError):
                events_list = []
        else:
            events_list = raw_events if isinstance(raw_events, list) else []

        if event in events_list:
            loop.create_task(_deliver(row["url"], payload))


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


def _row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a raw Piccolo CMSWebhook row to a JSON-serialisable dict."""
    result: dict[str, Any] = {}
    for key, value in row.items():
        if key == "events":
            if isinstance(value, str):
                try:
                    result[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    result[key] = []
            else:
                result[key] = value
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def make_webhook_routes(cms: CMS) -> list[Route]:
    """Build and return all webhook CRUD routes, closed over ``cms``."""

    async def list_webhooks(request: Request) -> JSONResponse:
        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        rows = await CMSWebhook.select().order_by(CMSWebhook.created_at, ascending=False).run()
        return JSONResponse({"webhooks": [_row_to_dict(r) for r in rows]})

    async def create_webhook(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        url = data.get("url")
        if not url:
            return JSONResponse({"error": "url is required"}, status_code=422)

        events = data.get("events")
        if not events:
            return JSONResponse(
                {"error": "events is required and must be a non-empty list"},
                status_code=422,
            )
        if not isinstance(events, list) or len(events) == 0:
            return JSONResponse(
                {"error": "events must be a non-empty list"},
                status_code=422,
            )

        webhook_id = generate(size=21)
        now = datetime.now(UTC)

        await CMSWebhook.insert(
            CMSWebhook(
                id=webhook_id,
                url=url,
                events=json.dumps(events),
                created_at=now,
                active=True,
            )
        ).run()

        rows = await CMSWebhook.select().where(CMSWebhook.id == webhook_id).run()
        return JSONResponse(_row_to_dict(rows[0]), status_code=201)

    async def delete_webhook(request: Request) -> Response:
        if (err := await require_auth(request, cms)) is not None:
            return err  # type: ignore[return-value]

        webhook_id = request.path_params["id"]
        rows = await CMSWebhook.select().where(CMSWebhook.id == webhook_id).run()
        if not rows:
            return JSONResponse({"error": "Webhook not found"}, status_code=404)

        await CMSWebhook.delete().where(CMSWebhook.id == webhook_id).run()
        return Response(status_code=204)

    return [
        Route("/api/webhooks", endpoint=list_webhooks, methods=["GET"]),
        Route("/api/webhooks", endpoint=create_webhook, methods=["POST"]),
        Route("/api/webhooks/{id}", endpoint=delete_webhook, methods=["DELETE"]),
    ]
