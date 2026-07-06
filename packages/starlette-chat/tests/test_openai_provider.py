"""
Tests for OpenAICompatibleProvider.

All tests mock the openai AsyncOpenAI client — no real API calls are made.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from starlette_chat.providers.base import StreamEvent


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_chunk(
    content: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Build a fake streaming chunk that looks like an openai ChatCompletionChunk."""
    chunk = MagicMock()
    choice = MagicMock()
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    choice.delta = delta
    choice.finish_reason = finish_reason
    chunk.choices = [choice]
    return chunk


def _make_tool_call_chunk(
    index: int,
    tool_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
    finish_reason: str | None = None,
) -> MagicMock:
    """Build a fake tool-call delta chunk."""
    tc = MagicMock()
    tc.index = index
    tc.id = tool_id
    fn = MagicMock()
    fn.name = name
    fn.arguments = arguments
    tc.function = fn
    return _make_chunk(tool_calls=[tc], finish_reason=finish_reason)


async def _fake_stream(chunks: list[MagicMock]) -> AsyncIterator:
    """Async generator that yields the given chunks."""
    for chunk in chunks:
        yield chunk


def _patch_openai(chunks: list[MagicMock]):
    """Context manager that patches openai.AsyncOpenAI to stream the given chunks."""
    mock_stream_cm = MagicMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=_fake_stream(chunks))
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.chat.completions.stream.return_value = mock_stream_cm

    mock_openai_cls = MagicMock(return_value=mock_client)
    return patch("openai.AsyncOpenAI", mock_openai_cls), mock_client


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_streams_text_tokens() -> None:
    chunks = [
        _make_chunk(content="Hello"),
        _make_chunk(content=" world"),
        _make_chunk(finish_reason="stop"),
    ]
    patcher, _ = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test", default_model="gpt-4o")
        events: list[StreamEvent] = []
        async for event in provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="",
            tools=[],
            model="gpt-4o",
            temperature=1.0,
            max_tokens=256,
        ):
            events.append(event)

    types = [e.type for e in events]
    assert "token" in types
    assert "done" in types
    tokens = [e.data["delta"] for e in events if e.type == "token"]
    assert "".join(tokens) == "Hello world"


@pytest.mark.asyncio
async def test_empty_content_skipped() -> None:
    """Empty content string should not produce token events."""
    chunks = [
        _make_chunk(content=""),
        _make_chunk(content=None),
        _make_chunk(content="hi", finish_reason="stop"),
    ]
    patcher, _ = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        events: list[StreamEvent] = []
        async for event in provider.stream([], "", [], "gpt-4o", 1.0, 256):
            events.append(event)

    tokens = [e for e in events if e.type == "token"]
    assert len(tokens) == 1
    assert tokens[0].data["delta"] == "hi"


@pytest.mark.asyncio
async def test_tool_call_assembled_and_emitted() -> None:
    """Tool call split across multiple chunks should be assembled and emitted complete."""
    chunks = [
        _make_tool_call_chunk(0, tool_id="tc_1", name="edit_document", arguments=""),
        _make_tool_call_chunk(0, arguments='{"markdown_content":'),
        _make_tool_call_chunk(0, arguments='"hello", "edit_rationale": "test"}'),
        _make_tool_call_chunk(0, finish_reason="tool_calls"),
    ]
    patcher, _ = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        events: list[StreamEvent] = []
        async for event in provider.stream([], "", [{"name": "edit_document"}], "gpt-4o", 1.0, 512):
            events.append(event)

    tool_events = [e for e in events if e.type == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0].data["tool"] == "edit_document"
    assert tool_events[0].data["input"]["markdown_content"] == "hello"
    assert tool_events[0].data["tool_use_id"] == "tc_1"

    done_events = [e for e in events if e.type == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_tool_call_bad_json_falls_back_to_empty_dict() -> None:
    chunks = [
        _make_tool_call_chunk(0, tool_id="tc_x", name="search_documents", arguments="{bad json"),
        _make_tool_call_chunk(0, finish_reason="tool_calls"),
    ]
    patcher, _ = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        events: list[StreamEvent] = []
        async for event in provider.stream([], "", [], "gpt-4o", 1.0, 256):
            events.append(event)

    tool_events = [e for e in events if e.type == "tool_use"]
    assert len(tool_events) == 1
    assert tool_events[0].data["input"] == {}


@pytest.mark.asyncio
async def test_system_prompt_prepended() -> None:
    """System prompt should be injected as the first message."""
    chunks = [_make_chunk(content="ok", finish_reason="stop")]
    patcher, mock_client = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        async for _ in provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="You are a helpful assistant.",
            tools=[],
            model="gpt-4o",
            temperature=1.0,
            max_tokens=256,
        ):
            pass

    call_kwargs = mock_client.chat.completions.stream.call_args[1]
    msgs = call_kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "You are a helpful assistant."}
    assert msgs[1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_no_system_prompt_not_prepended() -> None:
    chunks = [_make_chunk(content="ok", finish_reason="stop")]
    patcher, mock_client = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        async for _ in provider.stream(
            messages=[{"role": "user", "content": "hi"}],
            system_prompt="",
            tools=[],
            model="gpt-4o",
            temperature=1.0,
            max_tokens=256,
        ):
            pass

    call_kwargs = mock_client.chat.completions.stream.call_args[1]
    msgs = call_kwargs["messages"]
    assert msgs[0]["role"] == "user"
    assert not any(m["role"] == "system" for m in msgs)


@pytest.mark.asyncio
async def test_tools_wrapped_in_function_type() -> None:
    """Tools that are bare function dicts should be wrapped with type:'function'."""
    chunks = [_make_chunk(content="ok", finish_reason="stop")]
    patcher, mock_client = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        tools = [{"name": "search_documents", "description": "...", "input_schema": {}}]
        async for _ in provider.stream([], "", tools, "gpt-4o", 1.0, 256):
            pass

    call_kwargs = mock_client.chat.completions.stream.call_args[1]
    sent_tools = call_kwargs["tools"]
    assert sent_tools[0]["type"] == "function"


@pytest.mark.asyncio
async def test_no_tools_omits_tools_kwarg() -> None:
    """Empty tool list should result in no 'tools' kwarg being sent."""
    chunks = [_make_chunk(content="ok", finish_reason="stop")]
    patcher, mock_client = _patch_openai(chunks)
    with patcher:
        from starlette_chat.providers.openai import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(api_key="test")
        async for _ in provider.stream([], "", [], "gpt-4o", 1.0, 256):
            pass

    call_kwargs = mock_client.chat.completions.stream.call_args[1]
    assert "tools" not in call_kwargs


def test_for_lm_studio_classmethod() -> None:
    """for_lm_studio() sets the right base_url, api_key, and default_model."""
    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        from starlette_chat.providers.openai import OpenAICompatibleProvider, LM_STUDIO_BASE_URL

        provider = OpenAICompatibleProvider.for_lm_studio(model="qwen2.5-7b-instruct")
        assert provider._default_model == "qwen2.5-7b-instruct"
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["base_url"] == LM_STUDIO_BASE_URL
        assert call_kwargs["api_key"] == "lm-studio"


def test_missing_openai_package_raises() -> None:
    """ImportError with helpful message when openai isn't installed."""
    with patch.dict("sys.modules", {"openai": None}):
        import importlib
        import starlette_chat.providers.openai as mod
        importlib.reload(mod)
        with pytest.raises(ImportError, match="starlette-chat\\[openai\\]"):
            mod.OpenAICompatibleProvider(api_key="test")
