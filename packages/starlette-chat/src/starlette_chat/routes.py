"""
Route handlers for starlette-chat.

Three routes:
- POST /api/chat/sessions             — create a new chat session
- GET  /api/chat/sessions/{session_id} — fetch session + recent messages
- WS   /api/chat/sessions/{session_id}/ws — streaming conversation turn
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from .session import generate_session_slug
from .streaming import event_to_dict
from .tools import TOOL_DEFINITIONS, ToolDispatcher

if TYPE_CHECKING:
    from .app import ChatAPI


def _cms_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _cms_to_ws_base(cms_base: str) -> str:
    """Convert an HTTP CMS base URL to a WebSocket base URL."""
    if cms_base.startswith("https://"):
        return "wss://" + cms_base[len("https://"):]
    if cms_base.startswith("http://"):
        return "ws://" + cms_base[len("http://"):]
    return cms_base


def make_routes(chat: ChatAPI) -> list:
    """Return the route list for the ChatAPI Starlette app."""

    # ------------------------------------------------------------------
    # POST /api/chat/sessions
    # ------------------------------------------------------------------

    async def create_session(request: Request) -> JSONResponse:
        try:
            data = await request.json()
        except Exception:
            data = {}

        persona: str = data.get("persona", "default")
        doc_id: str | None = data.get("doc_id")

        headers = _cms_headers(chat._cms_api_key)

        async with httpx.AsyncClient() as client:
            # --- Find ModelConfig for this persona ---
            mc_resp = await client.get(
                f"{chat._cms_base}/api/documents",
                params={"doc_type": "model_config", "published": "true"},
                headers=headers,
            )
            model_config_doc_id: str | None = None
            if mc_resp.status_code == 200:
                mc_items = mc_resp.json()
                # Support both list and paginated responses
                if isinstance(mc_items, list):
                    docs = mc_items
                else:
                    docs = mc_items.get("items", mc_items.get("documents", []))
                for doc in docs:
                    body = doc.get("body") or {}
                    if isinstance(body, str):
                        try:
                            body = json.loads(body)
                        except Exception:
                            body = {}
                    if body.get("persona") == persona:
                        model_config_doc_id = doc.get("id")
                        break
                if model_config_doc_id is None and docs:
                    # Fall back to first doc (may have persona=="default")
                    model_config_doc_id = docs[0].get("id")

            # --- Find SystemPrompt for this persona ---
            sp_resp = await client.get(
                f"{chat._cms_base}/api/documents",
                params={"doc_type": "system_prompt", "published": "true"},
                headers=headers,
            )
            prompt_doc_id: str | None = None
            if sp_resp.status_code == 200:
                sp_items = sp_resp.json()
                if isinstance(sp_items, list):
                    docs = sp_items
                else:
                    docs = sp_items.get("items", sp_items.get("documents", []))
                for doc in docs:
                    body = doc.get("body") or {}
                    if isinstance(body, str):
                        try:
                            body = json.loads(body)
                        except Exception:
                            body = {}
                    if body.get("persona") == persona:
                        prompt_doc_id = doc.get("id")
                        break
                if prompt_doc_id is None and docs:
                    prompt_doc_id = docs[0].get("id")

            # --- Create ChatSession document ---
            slug = generate_session_slug()
            session_body: dict[str, Any] = {
                "persona": persona,
                "doc_ref": doc_id,
                "model_config_ref": model_config_doc_id,
                "prompt_ref": prompt_doc_id,
                "turn_count": 0,
            }
            create_resp = await client.post(
                f"{chat._cms_base}/api/documents",
                json={"doc_type": "chat_session", "body": session_body, "slug": slug},
                headers=headers,
            )
            if create_resp.status_code not in (200, 201):
                return JSONResponse(
                    {"error": "Failed to create session", "detail": create_resp.text},
                    status_code=502,
                )
            session_doc = create_resp.json()
            session_doc_id: str = session_doc["id"]

            # --- Publish the session doc ---
            await client.post(
                f"{chat._cms_base}/api/documents/{session_doc_id}/publish",
                headers=headers,
            )

        return JSONResponse(
            {"session_id": session_doc_id, "doc_id": doc_id},
            status_code=201,
        )

    # ------------------------------------------------------------------
    # GET /api/chat/sessions/{session_id}
    # ------------------------------------------------------------------

    async def get_session(request: Request) -> JSONResponse:
        session_id: str = request.path_params["session_id"]
        headers = _cms_headers(chat._cms_api_key)

        async with httpx.AsyncClient() as client:
            session_resp = await client.get(
                f"{chat._cms_base}/api/documents/{session_id}",
                headers=headers,
            )
            if session_resp.status_code == 404:
                return JSONResponse({"error": "Session not found"}, status_code=404)
            if session_resp.status_code != 200:
                return JSONResponse(
                    {"error": "Failed to load session"}, status_code=502
                )

            msgs_resp = await client.get(
                f"{chat._cms_base}/api/documents",
                params={
                    "doc_type": "chat_message",
                    "session_ref": session_id,
                    "limit": "50",
                },
                headers=headers,
            )
            messages: list[Any] = []
            if msgs_resp.status_code == 200:
                raw = msgs_resp.json()
                if isinstance(raw, list):
                    messages = raw
                else:
                    messages = raw.get("items", raw.get("documents", []))

        return JSONResponse(
            {
                "session": session_resp.json(),
                "messages": messages,
            }
        )

    # ------------------------------------------------------------------
    # WS /api/chat/sessions/{session_id}/ws
    # ------------------------------------------------------------------

    async def chat_ws(websocket: WebSocket) -> None:
        """Handle a streaming chat WebSocket connection."""
        session_id: str = websocket.path_params["session_id"]

        # Auth: check ?api_key= query param
        api_key = websocket.query_params.get("api_key", "")
        if api_key != chat._cms_api_key:
            await websocket.close(code=4403)
            return

        await websocket.accept()
        await websocket.send_json(
            {"type": "connected", "session_id": session_id}
        )

        headers = _cms_headers(chat._cms_api_key)
        collab_ws_base = _cms_to_ws_base(chat._cms_base)
        dispatcher = ToolDispatcher(
            cms_base=chat._cms_base,
            api_key=chat._cms_api_key,
            collab_ws_base=collab_ws_base,
        )

        try:
            while True:
                try:
                    msg = await websocket.receive_json()
                except Exception:
                    break

                if msg.get("type") != "message":
                    continue

                # Extract user content and context
                content: str = msg.get("content", "")
                context: dict[str, Any] = msg.get("context", {})

                await _handle_turn(
                    websocket=websocket,
                    session_id=session_id,
                    content=content,
                    context=context,
                    chat=chat,
                    headers=headers,
                    dispatcher=dispatcher,
                )

        finally:
            pass  # WebSocket cleaned up by Starlette on exit

    return [
        Route("/api/chat/sessions", endpoint=create_session, methods=["POST"]),
        Route(
            "/api/chat/sessions/{session_id}",
            endpoint=get_session,
            methods=["GET"],
        ),
        WebSocketRoute(
            "/api/chat/sessions/{session_id}/ws",
            endpoint=chat_ws,
        ),
    ]


# ------------------------------------------------------------------
# Turn handler — extracted for testability
# ------------------------------------------------------------------


async def _handle_turn(
    websocket: WebSocket,
    session_id: str,
    content: str,
    context: dict[str, Any],
    chat: Any,
    headers: dict[str, str],
    dispatcher: ToolDispatcher,
) -> None:
    """Process a single conversation turn."""
    system_prompt = ""
    model = "claude-sonnet-4-5"
    temperature: float = 1.0
    max_tokens: int = 4096

    async with httpx.AsyncClient() as client:
        # Load session document
        session_resp = await client.get(
            f"{chat._cms_base}/api/documents/{session_id}",
            headers=headers,
        )
        if session_resp.status_code != 200:
            await websocket.send_json(
                {"type": "error", "message": "Session not found"}
            )
            return

        session_doc = session_resp.json()
        session_body = session_doc.get("body") or {}
        if isinstance(session_body, str):
            try:
                session_body = json.loads(session_body)
            except Exception:
                session_body = {}

        # Load system prompt
        prompt_ref = session_body.get("prompt_ref")
        if prompt_ref:
            sp_resp = await client.get(
                f"{chat._cms_base}/api/documents/{prompt_ref}",
                headers=headers,
            )
            if sp_resp.status_code == 200:
                sp_body = sp_resp.json().get("body") or {}
                if isinstance(sp_body, str):
                    try:
                        sp_body = json.loads(sp_body)
                    except Exception:
                        sp_body = {}
                system_prompt = sp_body.get("content", "")

        # Load model config
        mc_ref = session_body.get("model_config_ref")
        if mc_ref:
            mc_resp = await client.get(
                f"{chat._cms_base}/api/documents/{mc_ref}",
                headers=headers,
            )
            if mc_resp.status_code == 200:
                mc_body = mc_resp.json().get("body") or {}
                if isinstance(mc_body, str):
                    try:
                        mc_body = json.loads(mc_body)
                    except Exception:
                        mc_body = {}
                model = mc_body.get("model_name", model)
                temperature = mc_body.get("temperature", temperature)
                max_tokens = mc_body.get("max_tokens", max_tokens)

        # Load message history
        msgs_resp = await client.get(
            f"{chat._cms_base}/api/documents",
            params={
                "doc_type": "chat_message",
                "session_ref": session_id,
                "limit": "50",
            },
            headers=headers,
        )
        history_docs: list[dict] = []
        if msgs_resp.status_code == 200:
            raw = msgs_resp.json()
            if isinstance(raw, list):
                history_docs = raw
            else:
                history_docs = raw.get("items", raw.get("documents", []))

        # Build messages list
        messages: list[dict[str, Any]] = []
        for hdoc in history_docs:
            hbody = hdoc.get("body") or {}
            if isinstance(hbody, str):
                try:
                    hbody = json.loads(hbody)
                except Exception:
                    hbody = {}
            role = hbody.get("role", "user")
            msg_content = hbody.get("content", "")
            messages.append({"role": role, "content": msg_content})

        # Append new user message
        turn_index = len(history_docs)
        messages.append({"role": "user", "content": content})

        # Signal thinking to browser
        await websocket.send_json({"type": "thinking"})

        # Persist user ChatMessage
        user_msg_resp = await client.post(
            f"{chat._cms_base}/api/documents",
            json={
                "doc_type": "chat_message",
                "body": {
                    "session_ref": session_id,
                    "role": "user",
                    "content": content,
                    "turn_index": turn_index,
                },
            },
            headers=headers,
        )
        # Increment turn count on session
        await client.patch(
            f"{chat._cms_base}/api/documents/{session_id}",
            json={"body": {"turn_count": turn_index + 1}},
            headers=headers,
        )

    # Determine provider
    provider = chat._provider
    if provider is None:
        try:
            from .providers.anthropic import AnthropicProvider

            provider = AnthropicProvider()
        except ImportError:
            await websocket.send_json(
                {
                    "type": "error",
                    "message": "No provider configured. Install starlette-chat[anthropic].",
                }
            )
            return

    # Stream from provider and forward events
    assistant_content_parts: list[str] = []
    steps_applied = 0

    async for event in await _aiter_stream(
        provider, messages, system_prompt, TOOL_DEFINITIONS, model, temperature, max_tokens
    ):
        event_dict = event_to_dict(event)
        await websocket.send_json(event_dict)

        if event.type == "token":
            assistant_content_parts.append(event.data.get("delta", ""))

        elif event.type == "tool_use":
            tool_name = event.data.get("tool", "")
            tool_input = event.data.get("input", {})
            # Inject doc_id from context if missing
            if "doc_id" not in tool_input and context.get("doc_id"):
                tool_input = dict(tool_input)
                tool_input["doc_id"] = context["doc_id"]

            result = await dispatcher.dispatch(tool_name, tool_input, context)

            # Send tool result to browser
            await websocket.send_json(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "summary": _summarise_tool_result(result),
                    "result": result,
                }
            )
            # Send "applying_edits" when edit_document is called
            if tool_name == "edit_document":
                await websocket.send_json(
                    {"type": "applying_edits", "doc_id": tool_input.get("doc_id", "")}
                )
                steps_applied = result.get("step_count", 0)

        elif event.type == "done":
            break

    # Persist assistant ChatMessage
    assistant_content = "".join(assistant_content_parts)
    assistant_turn_index = turn_index + 1

    async with httpx.AsyncClient() as client:
        assistant_msg_resp = await client.post(
            f"{chat._cms_base}/api/documents",
            json={
                "doc_type": "chat_message",
                "body": {
                    "session_ref": session_id,
                    "role": "assistant",
                    "content": assistant_content,
                    "turn_index": assistant_turn_index,
                    "model_used": model,
                    "steps_applied": steps_applied,
                },
            },
            headers=headers,
        )
        assistant_msg_id: str | None = None
        if assistant_msg_resp.status_code in (200, 201):
            assistant_msg_id = assistant_msg_resp.json().get("id")

    await websocket.send_json(
        {"type": "done", "message_id": assistant_msg_id}
    )


async def _aiter_stream(provider, messages, system_prompt, tools, model, temperature, max_tokens):
    """Normalise provider.stream() — supports both coroutine and async generator returns."""
    result = provider.stream(messages, system_prompt, tools, model, temperature, max_tokens)
    # If the provider returns a coroutine (async def ... -> AsyncIterator), await it first
    import inspect
    if inspect.iscoroutine(result):
        result = await result
    return result


def _summarise_tool_result(result: dict[str, Any]) -> str:
    """Build a human-readable one-line summary of a tool result."""
    status = result.get("status", "")
    if status == "accepted":
        n = result.get("step_count", 0)
        rationale = result.get("edit_rationale", "")
        return f"Applied {n} edit step(s): {rationale}"
    if status == "no_change":
        return result.get("message", "No changes")
    if status == "conflict":
        return result.get("message", "Version conflict")
    if status == "error":
        return result.get("message", "Error")
    if status == "published":
        return f"Published {result.get('doc_id', '')}"
    if status == "created":
        doc = result.get("document", {})
        return f"Created document {doc.get('id', '')}"
    if status == "ok":
        return "OK"
    return str(result)
