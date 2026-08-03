from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

# Default model used when no model_config doc is found in the CMS.
DEFAULT_MODEL = "claude-sonnet-4-5"


class BaseProvider(ABC):
    @abstractmethod
    def get_model(self) -> BaseChatModel:
        """Return a LangChain BaseChatModel instance for this provider.

        Used by the LangGraph agent loop in routes.py. The model is constructed
        with credentials and defaults from this provider's configuration.
        """
        ...
