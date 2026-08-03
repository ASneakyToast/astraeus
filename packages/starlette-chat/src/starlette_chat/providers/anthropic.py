"""
AnthropicProvider — wraps Claude as a LangChain BaseChatModel for use by the
LangGraph agent loop.

Install the ``anthropic`` extra to use this provider::

    pip install "starlette-chat[anthropic]"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette_chat.providers.base import DEFAULT_MODEL, BaseProvider

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class AnthropicProvider(BaseProvider):
    """Anthropic Claude provider.

    :param api_key: Anthropic API key.  Falls back to the ``ANTHROPIC_API_KEY``
        environment variable when ``None``.
    :param default_model: Default model identifier.
    """

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_MODEL,
    ) -> None:
        try:
            import langchain_anthropic  # noqa: F401 — validate extra is installed
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
