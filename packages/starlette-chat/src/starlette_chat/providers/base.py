from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any


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
