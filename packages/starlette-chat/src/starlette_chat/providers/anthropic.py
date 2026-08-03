"""
AnthropicProvider — streams Claude responses as :class:`StreamEvent` objects.

Install the ``anthropic`` extra to use this provider::

    pip install "starlette-chat[anthropic]"
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from starlette_chat.providers.base import BaseProvider, StreamEvent

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider backed by ``anthropic.AsyncAnthropic``.

    :param api_key: Anthropic API key.  Falls back to the ``ANTHROPIC_API_KEY``
        environment variable when ``None``.
    :param default_model: Default model identifier. Falls back to
        ``claude-sonnet-4-5`` when ``None``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = "claude-sonnet-4-5",
    ) -> None:
        try:
            import anthropic as _anthropic

            self._client = _anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "Install starlette-chat[anthropic] to use AnthropicProvider"
            ) from exc
        self._api_key = api_key
        self._default_model = default_model

    def get_model(self) -> BaseChatModel:
        """Return a LangChain ChatAnthropic instance for this provider."""
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=self._api_key,
            model=self._default_model,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream events from Claude.

        Yields :class:`StreamEvent` objects as the model produces output.
        ``tool_use`` events are complete — partial JSON is buffered internally
        and the event is only yielded once the full input is available.

        :param messages: Chat history in Anthropic format.
        :param system_prompt: System prompt text.
        :param tools: Tool definitions in Anthropic format.
        :param model: Model identifier (e.g. ``"claude-sonnet-4-5"``).
        :param temperature: Sampling temperature.
        :param max_tokens: Maximum tokens to generate.
        """
        # Pending tool-use block being assembled from partial_json deltas
        _pending_tool: dict[str, Any] | None = None
        _pending_tool_json: str = ""

        async with self._client.messages.stream(
            model=model or "claude-sonnet-4-5",
            max_tokens=max_tokens or 4096,
            system=system_prompt or "",
            messages=messages,
            tools=tools or [],
            temperature=temperature or 1.0,
        ) as stream:
            async for event in stream:
                if not hasattr(event, "type"):
                    continue

                etype = event.type

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block is None:
                        continue
                    btype = getattr(block, "type", None)

                    if btype == "thinking":
                        yield StreamEvent(type="thinking", data={})

                    elif btype == "tool_use":
                        _pending_tool = {
                            "tool": block.name,
                            "tool_use_id": block.id,
                        }
                        _pending_tool_json = ""

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta is None:
                        continue

                    if hasattr(delta, "text") and delta.text:
                        yield StreamEvent(
                            type="token", data={"delta": delta.text}
                        )
                    elif hasattr(delta, "partial_json") and delta.partial_json:
                        # Accumulate tool input JSON
                        _pending_tool_json += delta.partial_json

                elif etype == "content_block_stop":
                    # Emit complete tool_use now that input is fully buffered
                    if _pending_tool is not None:
                        try:
                            tool_input = (
                                json.loads(_pending_tool_json)
                                if _pending_tool_json
                                else {}
                            )
                        except json.JSONDecodeError:
                            tool_input = {}

                        yield StreamEvent(
                            type="tool_use",
                            data={
                                "tool": _pending_tool["tool"],
                                "tool_use_id": _pending_tool["tool_use_id"],
                                "input": tool_input,
                            },
                        )
                        _pending_tool = None
                        _pending_tool_json = ""

                elif etype == "message_stop":
                    yield StreamEvent(type="done", data={})
