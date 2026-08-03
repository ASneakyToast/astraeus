from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


@dataclass
class StreamEvent:
    type: str   # "thinking" | "token" | "tool_use" | "tool_result" | "done"
    data: dict[str, Any]


class BaseProvider(ABC):
    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        system_prompt: str,
        tools: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncIterator[StreamEvent]: ...

    @abstractmethod
    def get_model(self) -> BaseChatModel:
        """Return a LangChain BaseChatModel instance for this provider.

        Used by the LangGraph agent loop in routes.py. The model is constructed
        with credentials and defaults from this provider's configuration.
        """
        ...
