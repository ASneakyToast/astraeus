"""
OpenAICompatibleProvider — wraps any OpenAI-compatible API as a LangChain
BaseChatModel for use by the LangGraph agent loop.

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

from typing import TYPE_CHECKING

from starlette_chat.providers.base import BaseProvider

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# Default base URL for LM Studio's built-in OpenAI-compatible server.
LM_STUDIO_BASE_URL = "http://localhost:1234/v1"


class OpenAICompatibleProvider(BaseProvider):
    """Provider for any OpenAI-compatible chat-completions API.

    :param api_key: API key.  Defaults to the ``OPENAI_API_KEY`` environment
        variable.  For LM Studio, pass any non-empty string (e.g. ``"lm-studio"``).
    :param base_url: Base URL of the API.  Defaults to
        ``https://api.openai.com/v1``.  Set to ``"http://localhost:1234/v1"``
        for LM Studio, or use the :func:`for_lm_studio` class method.
    :param default_model: Model identifier passed to ``ChatOpenAI``.
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

    def get_model(self) -> BaseChatModel:
        """Return a LangChain ChatOpenAI instance for this provider."""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=self._client.api_key,
            base_url=str(self._client.base_url),
            model=self._default_model,
        )
