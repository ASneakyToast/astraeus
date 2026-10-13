"""MCP tools — driven end to end against the in-process CMS app."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from httpx import ASGITransport
from starlette_cms_feedback.mcp import server as mcp_module
from starlette_cms_feedback.mcp.server import build_feedback_mcp_server
from starlette_cms_feedback.models import FeedbackKind, FeedbackSeverity, FeedbackStatus

from .conftest import API_KEY

pytestmark = pytest.mark.asyncio


@pytest.fixture
def tools(feedback_app, monkeypatch) -> dict[str, Any]:
    """Tool callables for a server whose httpx client talks to the in-process app."""
    real_client = httpx.AsyncClient

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=ASGITransport(app=feedback_app["root"]), **kwargs)

    monkeypatch.setattr(mcp_module.httpx, "AsyncClient", client_factory)
    server = build_feedback_mcp_server(base_url="http://testserver/cms", api_key=API_KEY)
    return {name: tool.fn for name, tool in server._tool_manager._tools.items()}


async def test_registers_the_expected_tools(tools):
    assert set(tools) == {"file_feedback", "get_feedback", "list_feedback", "triage_feedback"}


async def test_tool_descriptions_name_every_enum_value(tools):
    """The docstrings spell out the vocabularies; this catches drift from the enums."""
    for enum, tool_name in (
        (FeedbackKind, "file_feedback"),
        (FeedbackSeverity, "file_feedback"),
        (FeedbackStatus, "triage_feedback"),
    ):
        doc = tools[tool_name].__doc__
        for member in enum:
            assert member.value in doc, f"{tool_name} docstring is missing {member.value!r}"


async def test_file_list_get_triage_round_trip(tools):
    filed = await tools["file_feedback"](
        kind="bug", title="Editor crashes", description="It broke.", component="starlette-editor"
    )
    assert filed["status"] == "new"

    listed = await tools["list_feedback"](status="new")
    assert [r["id"] for r in listed["reports"]] == [filed["id"]]

    triaged = await tools["triage_feedback"](
        report_id=filed["id"], status="in_progress", triage_notes="Looking."
    )
    assert triaged["status"] == "in_progress"

    fetched = await tools["get_feedback"](report_id=filed["id"])
    assert fetched["triage_notes"] == "Looking."


async def test_validation_failure_is_a_result_not_an_exception(tools):
    result = await tools["file_feedback"](kind="rant", title="x", description="y")

    assert result["error"] == "Validation failed"


async def test_get_missing_report_returns_error(tools):
    result = await tools["get_feedback"](report_id="nope")

    assert "not found" in result["error"]
