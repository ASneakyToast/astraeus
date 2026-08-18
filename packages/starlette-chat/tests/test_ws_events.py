"""
Unit tests for the LangGraph-event → WebSocket-message translation in routes.py.

Focus: on_tool_end must parse JSON tool output (true/false/null) into a real
dict so the summary names the result, instead of collapsing to ``{}``.
"""

from __future__ import annotations

import json

from starlette_chat.routes import _langgraph_event_to_ws, _summarise_tool_result


class _FakeToolMessage:
    """Stand-in for a LangChain ToolMessage — only ``.content`` is read."""

    def __init__(self, content: str) -> None:
        self.content = content


def test_on_tool_end_parses_json_content() -> None:
    """JSON tool output (with true/false/null) yields a populated result + summary."""
    content = json.dumps(
        {
            "status": "created",
            "document": {"id": "abc123", "slug": "wombats", "body": {"title": "Wombats"}},
            "published": False,  # JSON `false` — ast.literal_eval would choke on this
        }
    )
    event = {
        "event": "on_tool_end",
        "name": "create_document",
        "data": {"output": _FakeToolMessage(content)},
    }

    msg = _langgraph_event_to_ws(event)

    assert msg is not None
    assert msg["type"] == "tool_result"
    assert msg["tool"] == "create_document"
    # result is a real dict, not {}
    assert msg["result"]["status"] == "created"
    # summary names the created doc (prefers body.title)
    assert msg["summary"] == 'Created "Wombats"'


def test_on_tool_end_falls_back_to_literal_eval() -> None:
    """Python-repr'd dict content (single quotes) still parses via ast fallback."""
    event = {
        "event": "on_tool_end",
        "name": "search_documents",
        "data": {"output": _FakeToolMessage("{'status': 'ok'}")},
    }

    msg = _langgraph_event_to_ws(event)

    assert msg["result"] == {"status": "ok"}
    assert msg["summary"] == "OK"


def test_on_tool_end_unparseable_content_yields_empty_result() -> None:
    """Non-dict / garbage content degrades gracefully to an empty result."""
    event = {
        "event": "on_tool_end",
        "name": "noop",
        "data": {"output": _FakeToolMessage("not a dict at all")},
    }

    msg = _langgraph_event_to_ws(event)

    assert msg["result"] == {}


def test_summarise_created_prefers_title_then_slug() -> None:
    """created summary uses body.title, then slug, then id."""
    assert (
        _summarise_tool_result({"status": "created", "document": {"body": {"title": "Wombats"}}})
        == 'Created "Wombats"'
    )
    assert (
        _summarise_tool_result({"status": "created", "document": {"slug": "wombats", "body": {}}})
        == 'Created "wombats"'
    )
    assert (
        _summarise_tool_result({"status": "created", "document": {"id": "abc123", "body": {}}})
        == 'Created "abc123"'
    )
