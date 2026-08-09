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
from starlette_chat.providers.base import BaseProvider

__version__ = "0.1.0"


def register_blocks(cms: object) -> None:
    """Register all starlette-chat block types with a CMS instance.

    Includes chat_session and chat_message.  Prefer
    :func:`register_editorial_blocks` when ``ChatAPI`` is configured with
    a ``session_db_url`` — that keeps session/message runtime state out of
    the CMS document table and the changeset panel.

    Call this before accessing ``cms.app`` so that tables are created
    during CMS startup::

        register_blocks(cms)
        app.mount("/cms", app=cms.app)
    """
    cms.register_block(SystemPromptBlock)  # type: ignore[attr-defined]
    cms.register_block(ModelConfigBlock)   # type: ignore[attr-defined]
    cms.register_block(ChatSessionBlock)   # type: ignore[attr-defined]
    cms.register_block(ChatMessageBlock)   # type: ignore[attr-defined]


def register_editorial_blocks(cms: object) -> None:
    """Register only the editorial config block types (system_prompt, model_config).

    Use this instead of :func:`register_blocks` when ``ChatAPI`` is
    constructed with a ``session_db_url``.  Chat sessions and messages are
    then stored in a separate SQLite DB and never appear in CMS document
    lists or the changeset panel.  The editorial blocks (system_prompt,
    model_config) remain in the CMS because they are intentionally authored
    content, not runtime state::

        register_editorial_blocks(cms)  # before cms.app is accessed
        chat = ChatAPI(..., session_db_url="sqlite:///./chat.db")
        app.mount("/cms", app=cms.app)
        app.mount("/chat", app=chat.app)
    """
    cms.register_block(SystemPromptBlock)  # type: ignore[attr-defined]
    cms.register_block(ModelConfigBlock)   # type: ignore[attr-defined]


__all__ = [
    "ChatAPI",
    "register_blocks",
    "register_editorial_blocks",
    "ChatSessionBlock",
    "ChatMessageBlock",
    "SystemPromptBlock",
    "ModelConfigBlock",
    "BaseProvider",
]
