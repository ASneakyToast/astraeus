"""
Backend tests for Phase CH-3.

Tests:
1. test_create_session             — POST /api/chat/sessions returns 201 + session_id
2. test_create_session_no_config   — works even when no ModelConfig / SystemPrompt docs exist
3. test_ws_streams_tokens          — WS turn emits thinking, token, done in order
4. test_ws_edit_document_tool      — provider emits tool_use(edit_document), applying_edits sent
5. test_tool_search_documents      — dispatch search_documents hits GET /api/documents
6. test_tool_no_change             — diff_docs returns [] → no_change result, no WS opened
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport

from starlette_chat.app import ChatAPI
from starlette_chat.providers.base import BaseProvider, StreamEvent
from starlette_chat.tools import ToolDispatcher


# ---------------------------------------------------------------------------
# Mock provider helpers
# ---------------------------------------------------------------------------


class MockProvider(BaseProvider):
    """Provider that emits a preset list of StreamEvents."""

    def __init__(self, events: list[StreamEvent]) -> None:
        self._events = events

    async def stream(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        for event in self._events:
            yield event


def _token_events(text: str) -> list[StreamEvent]:
    return [
        StreamEvent(type="thinking", data={}),
        StreamEvent(type="token", data={"delta": text}),
        StreamEvent(type="done", data={}),
    ]


def _tool_events(tool_name: str, tool_input: dict) -> list[StreamEvent]:
    return [
        StreamEvent(type="thinking", data={}),
        StreamEvent(
            type="tool_use",
            data={"tool": tool_name, "tool_use_id": "tu_001", "input": tool_input},
        ),
        StreamEvent(type="token", data={"delta": "Done."}),
        StreamEvent(type="done", data={}),
    ]


# ---------------------------------------------------------------------------
# CMS mock helpers
# ---------------------------------------------------------------------------

CMS_BASE = "http://cms.local"
API_KEY = "test-api-key"


def _mock_empty_list() -> dict:
    return {"items": []}


def _session_doc(session_id: str, persona: str = "default") -> dict:
    return {
        "id": session_id,
        "doc_type": "chat_session",
        "body": {
            "persona": persona,
            "doc_ref": None,
            "model_config_ref": None,
            "prompt_ref": None,
            "turn_count": 0,
        },
    }


def _chat_message_doc(msg_id: str, role: str, content: str, turn_index: int) -> dict:
    return {
        "id": msg_id,
        "doc_type": "chat_message",
        "body": {
            "session_ref": "sess-1",
            "role": role,
            "content": content,
            "turn_index": turn_index,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_api() -> ChatAPI:
    return ChatAPI(
        cms_base_url=CMS_BASE,
        cms_api_key=API_KEY,
        provider=MockProvider(_token_events("Hello!")),
    )


@pytest_asyncio.fixture
async def chat_client(chat_api: ChatAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=chat_api.app),
        base_url="http://testserver",
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# 1. test_create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session(chat_api: ChatAPI) -> None:
    """POST /api/chat/sessions returns 201 with session_id; CMS create + publish called."""
    with respx.mock(base_url=CMS_BASE) as mock:
        # No ModelConfig or SystemPrompt
        mock.get("/api/documents").mock(return_value=httpx.Response(200, json=[]))
        # Create session doc
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json={"id": "sess-abc", "doc_type": "chat_session"})
        )
        # Publish session
        mock.post("/api/documents/sess-abc/publish").mock(
            return_value=httpx.Response(200, json={"id": "sess-abc"})
        )

        async with httpx.AsyncClient(
            transport=ASGITransport(app=chat_api.app),
            base_url="http://testserver",
        ) as client:
            resp = await client.post(
                "/api/chat/sessions",
                json={"persona": "default"},
            )

    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"] == "sess-abc"
    assert "doc_id" in body


# ---------------------------------------------------------------------------
# 2. test_create_session_no_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_no_config(chat_api: ChatAPI) -> None:
    """Session creation succeeds even when no ModelConfig / SystemPrompt documents exist."""
    with respx.mock(base_url=CMS_BASE) as mock:
        mock.get("/api/documents").mock(return_value=httpx.Response(200, json=[]))
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json={"id": "sess-xyz", "doc_type": "chat_session"})
        )
        mock.post("/api/documents/sess-xyz/publish").mock(
            return_value=httpx.Response(200, json={"id": "sess-xyz"})
        )

        async with httpx.AsyncClient(
            transport=ASGITransport(app=chat_api.app),
            base_url="http://testserver",
        ) as client:
            resp = await client.post(
                "/api/chat/sessions",
                json={"persona": "coding", "doc_id": None},
            )

    assert resp.status_code == 201
    assert resp.json()["session_id"] == "sess-xyz"


# ---------------------------------------------------------------------------
# 3. test_ws_streams_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_streams_tokens() -> None:
    """WS: connect, send message, receive thinking + token + done events in order."""
    provider = MockProvider(_token_events("Hello there!"))
    api = ChatAPI(cms_base_url=CMS_BASE, cms_api_key=API_KEY, provider=provider)

    with respx.mock(base_url=CMS_BASE) as mock:
        # Session load
        mock.get("/api/documents/sess-1").mock(
            return_value=httpx.Response(200, json=_session_doc("sess-1"))
        )
        # Message history (empty)
        mock.get("/api/documents").mock(return_value=httpx.Response(200, json=[]))
        # Persist user + assistant messages
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json={"id": "msg-1"})
        )
        # Session update (turn_count patch)
        mock.patch("/api/documents/sess-1").mock(
            return_value=httpx.Response(200, json=_session_doc("sess-1"))
        )

        from starlette.testclient import TestClient

        client = TestClient(api.app, raise_server_exceptions=True)
        with client.websocket_connect(
            f"/api/chat/sessions/sess-1/ws?api_key={API_KEY}"
        ) as ws:
            # First message should be "connected"
            connected = ws.receive_json()
            assert connected["type"] == "connected"
            assert connected["session_id"] == "sess-1"

            # Send a user message
            ws.send_json({"type": "message", "content": "Hi Claude"})

            events = []
            while True:
                msg = ws.receive_json()
                events.append(msg)
                if msg["type"] == "done":
                    break

    types = [e["type"] for e in events]
    assert "thinking" in types
    assert "token" in types
    assert types[-1] == "done"


# ---------------------------------------------------------------------------
# 4. test_ws_edit_document_tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ws_edit_document_tool() -> None:
    """WS: provider emits tool_use(edit_document) → applying_edits event sent to browser."""
    tool_input = {
        "markdown_content": "# Hello\n\nWorld.",
        "edit_rationale": "test edit",
        "doc_id": "doc-999",
    }
    provider = MockProvider(_tool_events("edit_document", tool_input))
    api = ChatAPI(cms_base_url=CMS_BASE, cms_api_key=API_KEY, provider=provider)

    with respx.mock(base_url=CMS_BASE) as mock:
        mock.get("/api/documents/sess-2").mock(
            return_value=httpx.Response(200, json=_session_doc("sess-2"))
        )
        mock.get("/api/documents").mock(return_value=httpx.Response(200, json=[]))
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json={"id": "msg-2"})
        )
        mock.patch("/api/documents/sess-2").mock(
            return_value=httpx.Response(200, json=_session_doc("sess-2"))
        )

        # Patch the ToolDispatcher._edit_document to avoid actual WS call
        with patch.object(
            ToolDispatcher,
            "_edit_document",
            new=AsyncMock(
                return_value={"status": "accepted", "step_count": 2, "edit_rationale": "test edit"}
            ),
        ):
            from starlette.testclient import TestClient

            client = TestClient(api.app, raise_server_exceptions=True)
            with client.websocket_connect(
                f"/api/chat/sessions/sess-2/ws?api_key={API_KEY}"
            ) as ws:
                _ = ws.receive_json()  # connected

                ws.send_json({
                    "type": "message",
                    "content": "Edit the doc",
                    "context": {"doc_id": "doc-999"},
                })

                events = []
                while True:
                    msg = ws.receive_json()
                    events.append(msg)
                    if msg["type"] == "done":
                        break

    types = [e["type"] for e in events]
    assert "applying_edits" in types, f"Expected applying_edits in {types}"
    assert "tool_result" in types


# ---------------------------------------------------------------------------
# 5. test_tool_search_documents
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_search_documents() -> None:
    """ToolDispatcher.dispatch('search_documents') hits GET /api/documents with params."""
    dispatcher = ToolDispatcher(
        cms_base=CMS_BASE,
        api_key=API_KEY,
        collab_ws_base="ws://cms.local",
    )

    with respx.mock(base_url=CMS_BASE) as mock:
        route = mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=[{"id": "doc-1"}])
        )
        result = await dispatcher.dispatch(
            "search_documents",
            {"doc_type": "blog_post", "published": True, "limit": 5},
            {},
        )

    assert result["status"] == "ok"
    assert route.called
    # Check that doc_type param was sent
    sent_params = dict(route.calls.last.request.url.params)
    assert sent_params.get("doc_type") == "blog_post"


# ---------------------------------------------------------------------------
# 6. test_tool_no_change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_no_change() -> None:
    """When diff_docs returns [] (identical docs), _edit_document returns no_change."""
    dispatcher = ToolDispatcher(
        cms_base=CMS_BASE,
        api_key=API_KEY,
        collab_ws_base="ws://cms.local",
    )

    # Build a PM doc and use it as both current and new
    from starlette_chat.prosemirror import markdown_to_pm

    md = "# Same heading\n\nSame paragraph."
    pm_doc = markdown_to_pm(md)

    with respx.mock(base_url=CMS_BASE) as mock:
        # _fetch_draft returns same doc as new_doc
        mock.get("/api/documents/doc-same").mock(
            return_value=httpx.Response(
                200,
                json={"id": "doc-same", "body": json.dumps(pm_doc)},
            )
        )

        # Provide same markdown → diff should be empty
        result = await dispatcher._edit_document(
            doc_id="doc-same",
            markdown_content=md,
            edit_rationale="no change test",
            context={},  # no draft_body in context → will fetch
        )

    assert result["status"] == "no_change"
