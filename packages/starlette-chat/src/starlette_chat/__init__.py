"""
starlette-chat — Governed AI chat collaborator for Astraeus.

A mountable Starlette sub-application providing a real-time AI chat
collaborator that participates in the ProseMirror WebSocket collab layer
as a first-class peer.

Quickstart::

    from starlette_chat import ChatAPI, register_blocks
    from starlette_chat.providers.anthropic import AnthropicProvider

    register_blocks(cms)   # before cms.app is accessed

    chat = ChatAPI(
        cms_base_url="http://localhost:8000/cms",
        cms_api_key="secret",
        provider=AnthropicProvider(api_key="anthropic-key"),
    )
    app.mount("/chat", app=chat.app)
"""

from __future__ import annotations

from starlette_chat.app import ChatAPI
from starlette_chat.blocks import (
    ChatMessageBlock,
    ChatSessionBlock,
    ModelConfigBlock,
    SystemPromptBlock,
)
from starlette_chat.providers.base import BaseProvider, StreamEvent

__version__ = "0.1.0"


def register_blocks(cms: object) -> None:
    """Register all starlette-chat block types with a CMS instance.

    Call this before accessing ``cms.app`` so that tables are created
    during CMS startup::

        register_blocks(cms)
        app.mount("/cms", app=cms.app)
    """
    cms.register_block(SystemPromptBlock)  # type: ignore[attr-defined]
    cms.register_block(ModelConfigBlock)   # type: ignore[attr-defined]
    cms.register_block(ChatSessionBlock)   # type: ignore[attr-defined]
    cms.register_block(ChatMessageBlock)   # type: ignore[attr-defined]


__all__ = [
    "ChatAPI",
    "register_blocks",
    "ChatSessionBlock",
    "ChatMessageBlock",
    "SystemPromptBlock",
    "ModelConfigBlock",
    "BaseProvider",
    "StreamEvent",
]
