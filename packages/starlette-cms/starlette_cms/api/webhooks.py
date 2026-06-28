"""Webhook registration and delivery — /api/webhooks"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from nanoid import generate
from opentelemetry import trace
from opentelemetry.trace import StatusCode
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from starlette_cms.auth import require_auth
from starlette_cms.tables import CMSWebhook

if TYPE_CHECKING:
    from starlette_cms.app import CMS

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


# ---------------------------------------------------------------------------
# Fire-and-forget delivery
# ---------------------------------------------------------------------------


async def _deliver(url: str, payload: dict[str, Any]) -> None:
    """POST *payload* to *url*; swallow transport errors and log failures."""
    event = payload.get("event", "")
    with tracer.start_as_current_span("cms.webhooks.deliver") as span:
        span.set_attribute("url", url)
        span.set_attribute("event", event)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    span.set_status(StatusCode.ERROR, f"HTTP {resp.status_code}")
                    logger.warning(
                        "starlette_cms.webhook.delivery_failed",
                        url=url,
                        event=event,
                        status_code=resp.status_code,
                    )
                else:
                    logger.debug(
                        "starlette_cms.webhook.delivered",
                        url=url,
                        event=event,
                        status_code=resp.status_code,
                    )
        except Exception as exc:  # noqa: BLE001
            span.set_status(StatusCode.ERROR, str(exc))
            logger.warning(
                "starlette_cms.webhook.delivery_error",
                url=url,
                event=event,
                exc_info=exc,
            )


async def fire_event(
    cms: CMS,  # noqa: ARG001 — kept for future use (per-cms filtering)
    event: str,
    doc_id: str,
    doc_type: str,
    slug: str,
    *,
    extra: dict[str, Any] | None = None,
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
    :param extra: Optional extra fields merged into the webhook payload
        (e.g. ``{"singleton": True}``).
    """
    rows = await CMSWebhook.select().where(CMSWebhook.active == True).run()  # noqa: E712

    payload: dict[str, Any] = {
        "event": event,
        "document_id": doc_id,
        "document_type": doc_type,
        "slug": slug,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if extra:
        payload.update(extra)

    loop = asyncio.get_running_loop()
    for row in rows:
        raw_events = row.get("events", "[]")
        if isinstance(raw_events, str):
            try:
                events_list = json.loads(raw_events)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "starlette_cms.webhooks.events_parse_failed",
                    webhook_id=row.get("id"),
                )
                events_list = []
        else:
            events_list = raw_events if isinstance(raw_events, list) else []

        if event in events_list:
            task = loop.create_task(_deliver(row["url"], payload))
            # Prevent unhandled-task-exception warnings; _deliver logs its own errors
            task.add_done_callback(
                lambda t: t.exception() if not t.cancelled() else None
            )


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
                    logger.warning(
                        "starlette_cms.webhooks.row_field_parse_failed",
                        key=key,
                    )
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
