"""
Feedback API — registered on the CMS as extension routes.

Routes added to the CMS:
  GET   /api/feedback        — list reports (filters: status, kind, component)
  POST  /api/feedback        — file a report (always starts as ``new``)
  GET   /api/feedback/{id}   — one report
  PATCH /api/feedback/{id}   — triage: status, severity, triage_notes

Every route requires the CMS's own auth (``Authorization: Bearer <api_key>`` or
a session cookie), reads included. Reports are never served unauthenticated.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette_cms.auth import require_auth

from starlette_cms_feedback.models import (
    FeedbackCreate,
    FeedbackKind,
    FeedbackStatus,
    FeedbackUpdate,
)

if TYPE_CHECKING:
    from starlette_cms_feedback.admin.app import FeedbackAdmin


def _validation_error(exc: ValidationError) -> JSONResponse:
    detail = exc.errors(include_url=False, include_context=False, include_input=False)
    return JSONResponse({"error": "Validation failed", "detail": detail}, status_code=422)


async def _read_json_object(request: Request) -> dict[str, Any] | None:
    """Parse the request body as a JSON object, or ``None`` if it isn't one."""
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def make_feedback_api_routes(admin: FeedbackAdmin) -> list[Route]:
    """
    Return the CMS extension routes for the feedback API.

    All routes close over *admin* to share its CMS reference and store.
    """
    cms = admin.cms
    store = admin.store

    async def list_feedback(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        params = request.query_params
        try:
            kind = FeedbackKind(params["kind"]) if "kind" in params else None
            status = FeedbackStatus(params["status"]) if "status" in params else None
            limit = int(params.get("limit", 50))
            offset = int(params.get("offset", 0))
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        reports, total = await store.list_reports(
            component=params.get("component"),
            kind=kind,
            limit=limit,
            offset=offset,
            status=status,
        )
        return JSONResponse(
            {
                "limit": limit,
                "offset": offset,
                "reports": [r.model_dump(mode="json") for r in reports],
                "total": total,
            }
        )

    async def create_feedback(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        raw = await _read_json_object(request)
        if raw is None:
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)

        try:
            data = FeedbackCreate.model_validate(raw)
        except ValidationError as exc:
            return _validation_error(exc)

        report = await store.create(data)
        return JSONResponse(report.model_dump(mode="json"), status_code=201)

    async def get_feedback(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        report_id = request.path_params["id"]
        report = await store.get(report_id)
        if report is None:
            return JSONResponse({"error": f"Report {report_id!r} not found."}, status_code=404)
        return JSONResponse(report.model_dump(mode="json"))

    async def update_feedback(request: Request) -> JSONResponse:
        if (err := await require_auth(request, cms)) is not None:
            return err

        raw = await _read_json_object(request)
        if raw is None:
            return JSONResponse({"error": "Body must be a JSON object"}, status_code=400)

        try:
            changes = FeedbackUpdate.model_validate(raw)
        except ValidationError as exc:
            return _validation_error(exc)

        report_id = request.path_params["id"]
        report = await store.update(report_id, changes)
        if report is None:
            return JSONResponse({"error": f"Report {report_id!r} not found."}, status_code=404)
        return JSONResponse(report.model_dump(mode="json"))

    return [
        Route(
            "/api/feedback",
            endpoint=list_feedback,
            methods=["GET"],
            name="feedback_list",
        ),
        Route(
            "/api/feedback",
            endpoint=create_feedback,
            methods=["POST"],
            name="feedback_create",
        ),
        Route(
            "/api/feedback/{id}",
            endpoint=get_feedback,
            methods=["GET"],
            name="feedback_detail",
        ),
        Route(
            "/api/feedback/{id}",
            endpoint=update_feedback,
            methods=["PATCH"],
            name="feedback_update",
        ),
    ]
