"""
OpenAICompatibleProvider — streams responses from any OpenAI-compatible API as
:class:`StreamEvent` objects.

Works with the OpenAI API, Azure OpenAI, and any local server that speaks the
OpenAI chat-completions wire format — including **LM Studio** (default base URL:
``http://localhost:1234/v1``).

Install the ``openai`` extra to use this provider::

    pip install "starlette-chat[openai]"

Usage with LM Studio::

    from starlette_chat.providers.openai import OpenAICompatibleProvider

    provider = OpenAICompatibleProvider(
        base_url="http://localhost:1234/v1",
        api_key="lm-studio",                    # LM Studio ignores the key
        default_model="mistral-nemo-instruct",   # whatever model you have loaded
    )

Usage with the OpenAI API::

    provider = OpenAICompatibleProvider(
        api_key="sk-...",
        default_model="gpt-4o",
    )
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from starlette_chat.providers.base import BaseProvider, StreamEvent

# Models known to support tool calling reliably with local LM Studio installs.
# This is purely informational — any model string is accepted.
TOOL_CAPABLE_MODELS = (
    "mistral-nemo-instruct",
    "mistral-7b-instruct",
    "qwen2.5-7b-instruct",
    "qwen2.5-14b-instruct",
    "llama-3.1-8b-instruct",
    "llama-3.1-70b-instruct",
    "llama-3.3-70b-instruct",
)

# Default base URL for LM Studio's built-in OpenAI-compatible server.
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"


class OpenAICompatibleProvider(BaseProvider):
    """Provider for any OpenAI-compatible chat-completions API.

    :param api_key: API key.  Defaults to the ``OPENAI_API_KEY`` environment
        variable.  For LM Studio, pass any non-empty string (e.g. ``"lm-studio"``).
    :param base_url: Base URL of the API.  Defaults to
        ``https://api.openai.com/v1``.  Set to ``"http://localhost:1234/v1"``
        for LM Studio, or use the :func:`for_lm_studio` class method.
    :param default_model: Model identifier used when ``stream()`` is called
        with an empty ``model`` argument.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str = "gpt-4o",
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise ImportError(
                "Install starlette-chat[openai] to use OpenAICompatibleProvider"
            ) from exc

        self._default_model = default_model
        self._client = AsyncOpenAI(  # type: ignore[call-arg]
            api_key=api_key or "placeholder",
            base_url=base_url,
        )

    @classmethod
    def for_lm_studio(
        cls,
        base_url: str = LM_STUDIO_BASE_URL,
        model: str = "local-model",
    ) -> OpenAICompatibleProvider:
        """Convenience constructor for LM Studio.

        :param base_url: LM Studio server URL.  Defaults to
            ``http://localhost:1234/v1``.
        :param model: Model identifier as shown in LM Studio's model list.
            Passed verbatim to the completions endpoint — use the exact string
            LM Studio reports (e.g. ``"mistral-nemo-instruct-2407"``).

        ::

            provider = OpenAICompatibleProvider.for_lm_studio(
                model="qwen2.5-7b-instruct"
            )
        """
        return cls(api_key="lm-studio", base_url=base_url, default_model=model)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]:
        """Stream events from an OpenAI-compatible endpoint.

        Yields :class:`StreamEvent` objects as the model produces output.
        ``tool_use`` events are complete — partial tool-call JSON is buffered
        internally and the event is only yielded once the full arguments are
        available.

        :param messages: Chat history in OpenAI format
            (``[{"role": "user", "content": "..."}]``).
        :param system_prompt: System prompt text.
        :param tools: Tool definitions in OpenAI format.
        :param model: Model identifier.  Falls back to ``default_model`` when
            empty.
        :param temperature: Sampling temperature.
        :param max_tokens: Maximum tokens to generate.
        """
        full_messages: list[dict[str, Any]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # Convert tool definitions to OpenAI format (they arrive in our
        # internal format which matches OpenAI's schema already).
        openai_tools = (
            [
                {"type": "function", "function": t}
                if "function" not in t
                else t
                for t in tools
            ]
            if tools
            else []
        )

        kwargs: dict[str, Any] = dict(
            model=model or self._default_model,
            messages=full_messages,
            temperature=temperature or 1.0,
            max_tokens=max_tokens or 4096,
            stream=True,
        )
        if openai_tools:
            kwargs["tools"] = openai_tools
            kwargs["tool_choice"] = "auto"

        # Pending tool-call being assembled from streamed chunks
        _pending_calls: dict[int, dict[str, Any]] = {}  # index → call state

        async with self._client.chat.completions.stream(**kwargs) as stream:  # type: ignore[attr-defined]
            async for chunk in stream:
                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                finish_reason = chunk.choices[0].finish_reason

                # ── Text tokens ──────────────────────────────────────────────
                if delta.content:
                    yield StreamEvent(type="token", data={"delta": delta.content})

                # ── Tool call chunks ─────────────────────────────────────────
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in _pending_calls:
                            _pending_calls[idx] = {
                                "id": tc.id or "",
                                "name": "",
                                "arguments": "",
                            }
                        call = _pending_calls[idx]
                        if tc.id:
                            call["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                call["name"] += tc.function.name
                            if tc.function.arguments:
                                call["arguments"] += tc.function.arguments

                # ── Emit complete tool calls on finish ───────────────────────
                if finish_reason in ("tool_calls", "stop") and _pending_calls:
                    import json

                    for call in _pending_calls.values():
                        try:
                            parsed_input = (
                                json.loads(call["arguments"])
                                if call["arguments"]
                                else {}
                            )
                        except json.JSONDecodeError:
                            parsed_input = {}

                        yield StreamEvent(
                            type="tool_use",
                            data={
                                "tool": call["name"],
                                "tool_use_id": call["id"],
                                "input": parsed_input,
                            },
                        )
                    _pending_calls.clear()

                if finish_reason in ("stop", "tool_calls", "length", "end_turn"):
                    yield StreamEvent(type="done", data={})
                    return

        # Fallback done in case stream ends without an explicit finish_reason
        if _pending_calls:
            import json

            for call in _pending_calls.values():
                try:
                    parsed_input = (
                        json.loads(call["arguments"]) if call["arguments"] else {}
                    )
                except json.JSONDecodeError:
                    parsed_input = {}

                yield StreamEvent(
                    type="tool_use",
                    data={
                        "tool": call["name"],
                        "tool_use_id": call["id"],
                        "input": parsed_input,
                    },
                )

        yield StreamEvent(type="done", data={})
