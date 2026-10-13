"""
MCP server for starlette-cms-feedback (ADR 005).

All tools are thin wrappers around the feedback HTTP API registered on the CMS
by :class:`~starlette_cms_feedback.FeedbackAdmin`. No business logic lives
here — only tool definitions and httpx calls.

Requires ``pip install starlette-cms-feedback[mcp]``.

Usage::

    from starlette_cms_feedback.mcp.server import build_feedback_mcp_server

    server = build_feedback_mcp_server(
        base_url="https://cms.example.com/cms",
        api_key="secret",
    )
    server.run(transport="stdio")
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from pydantic import Field

try:
    from mcp.server.fastmcp import FastMCP
    from starlette_cms.mcp.server import (
        CREATE,
        DEFAULT_LIST_LIMIT,
        MAX_LIST_LIMIT,
        READ_ONLY,
        UPDATE,
        _reject_unknown_arguments,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "The MCP server requires the 'mcp' extra. "
        "Install with: pip install starlette-cms-feedback[mcp]"
    ) from exc


# What list_feedback returns per report; the long free-text fields come from get_feedback.
SUMMARY_FIELDS = ("component", "created_at", "id", "kind", "severity", "status", "title")


def build_feedback_mcp_server(base_url: str, api_key: str | None = None) -> FastMCP:
    """
    Build and return a FastMCP server wired to the feedback HTTP API.

    :param base_url: Base URL of the CMS the feedback routes are registered
        on, including its mount path, e.g. ``https://mysite.com/cms``.  Must
        not have a trailing slash.
    :param api_key: CMS API key, sent as ``Authorization: Bearer``.  The
        feedback API requires auth for reads as well as writes.

    The httpx client is created lazily on the first tool call so the server
    can be imported without making any network connections.
    """

    _client: httpx.AsyncClient | None = None

    def _get_client() -> httpx.AsyncClient:
        nonlocal _client
        if _client is None or _client.is_closed:
            headers: dict[str, str] = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            _client = httpx.AsyncClient(base_url=base_url, headers=headers, timeout=30.0)
        return _client

    def _error(response: httpx.Response, report_id: str | None = None) -> dict[str, Any] | None:
        """Translate a failed response to a tool result, or ``None`` if it succeeded."""
        if response.status_code == 404:
            return {"error": f"Report {report_id!r} not found"}
        if response.status_code in (400, 422):
            return {"error": "Validation failed", "detail": response.json()}
        response.raise_for_status()
        return None

    mcp = FastMCP(
        name="starlette-cms-feedback",
        instructions=(
            "Tools for filing and triaging feedback and bug reports. "
            "file_feedback records a report; list_feedback and get_feedback read them; "
            "triage_feedback changes status, severity and triage notes. "
            "A report's description is the reporter's words and is never edited — "
            "put your own findings in triage_notes."
        ),
    )

    @mcp.tool(annotations=CREATE)
    async def file_feedback(
        kind: str,
        title: str,
        description: str,
        component: str | None = None,
        severity: str | None = None,
        steps_to_reproduce: str | None = None,
        expected: str | None = None,
        actual: str | None = None,
        environment: str | None = None,
        reporter: str | None = None,
    ) -> dict[str, Any]:
        """
        File a new feedback report or bug report. It starts with status ``new``.

        :param kind: One of: bug, feedback, idea.
        :param title: One-line summary (max 200 characters).
        :param description: What happened, or what you want.
        :param component: Which package or area, e.g. ``"starlette-editor"``.
        :param severity: One of: low, medium, high, blocking.  Mostly useful for bugs.
        :param steps_to_reproduce: How to trigger a bug.
        :param expected: What should have happened.
        :param actual: What happened instead.
        :param environment: Versions, browser, OS — whatever helps reproduce.
        :param reporter: Who is filing this.
        """
        payload = {
            "actual": actual,
            "component": component,
            "description": description,
            "environment": environment,
            "expected": expected,
            "kind": kind,
            "reporter": reporter,
            "severity": severity,
            "steps_to_reproduce": steps_to_reproduce,
            "title": title,
        }
        r = await _get_client().post(
            "/api/feedback", json={k: v for k, v in payload.items() if v is not None}
        )
        if (err := _error(r)) is not None:
            return err
        return r.json()

    @mcp.tool(annotations=READ_ONLY)
    async def list_feedback(
        status: str | None = None,
        kind: str | None = None,
        component: str | None = None,
        limit: Annotated[int, Field(ge=1, le=MAX_LIST_LIMIT)] = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List feedback reports as short summaries, newest first.

        Each summary has the id, title, kind, status, severity, component and
        created_at — not the description or steps. Use get_feedback for those.
        Returns ``reports``, ``total`` (all matches, ignoring limit/offset),
        ``limit`` and ``offset``.

        :param status: Filter by status — one of: new, triaged, in_progress, fixed, wontfix.
        :param kind: Filter by kind — one of: bug, feedback, idea.
        :param component: Filter to one component, exact match.
        :param limit: Max reports to return (1-50, default 10).
        :param offset: Reports to skip, for pagination.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        for name, value in (("component", component), ("kind", kind), ("status", status)):
            if value is not None:
                params[name] = value
        r = await _get_client().get("/api/feedback", params=params)
        if (err := _error(r)) is not None:
            return err
        data = r.json()
        data["reports"] = [
            {name: report[name] for name in SUMMARY_FIELDS} for report in data["reports"]
        ]
        return data

    @mcp.tool(annotations=READ_ONLY)
    async def get_feedback(report_id: str) -> dict[str, Any]:
        """
        Return one feedback report by id, with all its fields.

        :param report_id: The report's id (from list_feedback).
        """
        r = await _get_client().get(f"/api/feedback/{report_id}")
        if (err := _error(r, report_id)) is not None:
            return err
        return r.json()

    @mcp.tool(annotations=UPDATE)
    async def triage_feedback(
        report_id: str,
        status: str | None = None,
        severity: str | None = None,
        triage_notes: str | None = None,
    ) -> dict[str, Any]:
        """
        Update a report's triage state. Only the fields you pass change.

        :param report_id: The report's id.
        :param status: New status — one of: new, triaged, in_progress, fixed, wontfix.
        :param severity: New severity — one of: low, medium, high, blocking.
        :param triage_notes: Your findings: cause, fix, links, why it was closed.
            Replaces any existing notes.
        """
        payload = {"severity": severity, "status": status, "triage_notes": triage_notes}
        r = await _get_client().patch(
            f"/api/feedback/{report_id}",
            json={k: v for k, v in payload.items() if v is not None},
        )
        if (err := _error(r, report_id)) is not None:
            return err
        return r.json()

    _reject_unknown_arguments(mcp)  # a misnamed argument must fail, not be silently dropped

    return mcp
