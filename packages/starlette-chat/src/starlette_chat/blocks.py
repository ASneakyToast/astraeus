"""
Block definitions for starlette-chat.

Four block types representing the chat data model:

- ChatSessionBlock  — mutable conversation session record
- ChatMessageBlock  — immutable audit record (append_only=True)
- SystemPromptBlock — versioned system prompt per persona
- ModelConfigBlock  — versioned model configuration per persona

Register all four with a CMS instance using::

    from starlette_chat import register_blocks
    register_blocks(cms)
"""

from __future__ import annotations

from starlette_cms import DocumentRef, NumberField, SelectField, TextField
from starlette_cms.registry import block

_PERSONA_CHOICES = ["default", "support", "coding", "creative"]


@block("chat_session")
class ChatSessionBlock:
    """Mutable conversation session — title and summary can be updated."""

    persona: str = SelectField(choices=_PERSONA_CHOICES)
    user_id: str = TextField(required=False)
    title: str = TextField(required=False)
    doc_ref: str = DocumentRef(block_type="*", on_delete="nullify", required=False)
    doc_version: int = NumberField(required=False)
    model_config_ref: str = DocumentRef(block_type="model_config", on_delete="nullify")
    prompt_ref: str = DocumentRef(block_type="system_prompt", on_delete="nullify")
    summary: str = TextField(required=False)
    turn_count: int = NumberField(default=0)


@block("chat_message", append_only=True)
class ChatMessageBlock:
    """Immutable audit record — written once, never modified."""

    session_ref: str = DocumentRef(block_type="chat_session", on_delete="cascade")
    role: str = SelectField(choices=["user", "assistant", "tool"])
    content: str = TextField(required=True)
    turn_index: int = NumberField(required=True)
    # tool use
    tool_name: str = TextField(required=False)
    tool_call_id: str = TextField(required=False)
    # telemetry (assistant messages only)
    model_used: str = TextField(required=False)
    prompt_tokens: int = NumberField(required=False)
    completion_tokens: int = NumberField(required=False)
    latency_ms: int = NumberField(required=False)
    steps_applied: int = NumberField(required=False)


@block("system_prompt")
class SystemPromptBlock:
    """Versioned system prompt.  Multiple personas are supported."""

    persona: str = SelectField(choices=_PERSONA_CHOICES)
    content: str = TextField(required=True)
    change_rationale: str = TextField(required=True)
    authored_by: str = TextField(required=True)
    version_notes: str = TextField(required=False)


@block("model_config")
class ModelConfigBlock:
    """Versioned model configuration.  Multiple personas are supported."""

    persona: str = SelectField(choices=_PERSONA_CHOICES)
    provider: str = SelectField(choices=["anthropic", "openai"])
    model_name: str = TextField(required=True)
    temperature: float = NumberField(min_value=0.0, max_value=2.0, precision=2, default=1.0)
    max_tokens: int = NumberField(min_value=1, max_value=32768, default=4096)
    system_prompt_ref: str = DocumentRef(block_type="system_prompt", on_delete="nullify")
