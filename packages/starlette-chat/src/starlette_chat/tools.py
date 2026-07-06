"""
Chat tool dispatcher.

Implements the curated AI tool suite scoped to the editing session.
Tools are thin wrappers over the existing CMS and mediakit HTTP APIs
plus the ProseMirror collab WebSocket for edit operations.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


# ---------------------------------------------------------------------------
# Tool definitions — passed to the LLM provider
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "edit_document",
        "description": (
            "Apply edits to the document being edited. Write changes as Markdown — "
            "translation to live format is automatic. Other editors see your changes "
            "in real time."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "markdown_content": {
                    "type": "string",
                    "description": "Full document or changed section in Markdown",
                },
                "edit_rationale": {
                    "type": "string",
                    "description": "Brief description of what changed and why",
                },
                "scope": {
                    "type": "string",
                    "enum": ["full", "selection"],
                    "description": (
                        "Whether markdown_content is the full doc or just the "
                        "selected section"
                    ),
                },
            },
            "required": ["markdown_content", "edit_rationale"],
        },
    },
    {
        "name": "search_documents",
        "description": "Find existing documents by type or content",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string"},
                "published": {"type": "boolean"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "publish_document",
        "description": "Publish the document. This triggers a site rebuild.",
        "input_schema": {
            "type": "object",
            "properties": {"doc_id": {"type": "string"}},
            "required": ["doc_id"],
        },
    },
    {
        "name": "get_available_doc_types",
        "description": "List all document types and their fields",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_document",
        "description": "Create a new document",
        "input_schema": {
            "type": "object",
            "properties": {
                "doc_type": {"type": "string"},
                "body": {"type": "object"},
                "slug": {"type": "string"},
            },
            "required": ["doc_type", "body", "slug"],
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class ToolDispatcher:
    """Dispatch AI tool calls to the appropriate backend.

    :param cms_base: HTTP base URL for the CMS API (e.g. ``http://localhost:8000/cms``).
    :param api_key: API key for CMS authentication.
    :param collab_ws_base: WebSocket base URL for the collab endpoint
        (e.g. ``ws://localhost:8000/cms``).
    """

    def __init__(
        self,
        cms_base: str,
        api_key: str,
        collab_ws_base: str,
    ) -> None:
        self._cms_base = cms_base.rstrip("/")
        self._api_key = api_key
        self._collab_ws_base = collab_ws_base.rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def dispatch(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Route a tool call to the appropriate implementation.

        :param tool_name: Tool name as defined in ``TOOL_DEFINITIONS``.
        :param tool_input: Tool input dict from the LLM.
        :param context: Session context — may contain ``doc_id``, ``version``,
            ``draft_body``, ``selection``.
        :returns: Result dict forwarded back to the LLM as a tool result.
        """
        if tool_name == "edit_document":
            doc_id = tool_input.get("doc_id") or context.get("doc_id")
            if not doc_id:
                return {"status": "error", "message": "No doc_id in context or tool input"}
            return await self._edit_document(
                doc_id=doc_id,
                markdown_content=tool_input["markdown_content"],
                edit_rationale=tool_input.get("edit_rationale", ""),
                context=context,
            )

        elif tool_name == "search_documents":
            return await self._search_documents(tool_input)

        elif tool_name == "search_media":
            return await self._search_media(tool_input)

        elif tool_name == "get_available_doc_types":
            return await self._get_available_doc_types()

        elif tool_name == "get_document_history":
            return await self._get_document_history(tool_input)

        elif tool_name == "publish_document":
            return await self._publish_document(tool_input)

        elif tool_name == "create_document":
            return await self._create_document(tool_input)

        elif tool_name == "add_to_changeset":
            return await self._add_to_changeset(tool_input)

        else:
            return {"status": "error", "message": f"Unknown tool: {tool_name}"}

    # ------------------------------------------------------------------
    # edit_document
    # ------------------------------------------------------------------

    async def _edit_document(
        self,
        doc_id: str,
        markdown_content: str,
        edit_rationale: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply edits to a live document via the collab WebSocket."""
        from .diff import diff_docs
        from .prosemirror import markdown_to_pm

        import websockets

        current_draft = context.get("draft_body") or await self._fetch_draft(doc_id)
        new_doc = markdown_to_pm(markdown_content)
        steps = diff_docs(current_draft, new_doc)

        if not steps:
            return {"status": "no_change", "message": "No differences found"}

        ws_url = (
            f"{self._collab_ws_base}/api/documents/{doc_id}/collab"
            f"?api_key={self._api_key}"
        )

        for attempt in range(2):
            try:
                async with websockets.connect(ws_url) as ws:
                    # Send presence as AI client
                    await ws.send(
                        json.dumps(
                            {
                                "type": "presence",
                                "display": "Claude",
                                "client_type": "ai",
                            }
                        )
                    )
                    # Wait for init
                    init = json.loads(await ws.recv())
                    server_version = init.get("version", 0)

                    # Send editing status
                    await ws.send(json.dumps({"type": "editing", "doc_id": doc_id}))

                    # Submit steps
                    await ws.send(
                        json.dumps(
                            {
                                "type": "steps",
                                "steps": steps,
                                "clientID": "claude-assistant",
                                "version": server_version,
                                "doc": new_doc,
                            }
                        )
                    )

                    # Wait for confirm or reject
                    result = json.loads(await ws.recv())
                    await ws.send(json.dumps({"type": "editing_done"}))

            except Exception as exc:
                return {"status": "error", "message": str(exc)}

            if result.get("type") == "steps":
                return {
                    "status": "accepted",
                    "step_count": len(steps),
                    "edit_rationale": edit_rationale,
                }

            # On reject: re-fetch current doc and re-diff
            if attempt == 0:
                current_draft = await self._fetch_draft(doc_id)
                steps = diff_docs(current_draft, new_doc)
                if not steps:
                    return {
                        "status": "no_change",
                        "message": "No differences after re-fetch",
                    }

        return {
            "status": "conflict",
            "message": "Version conflict after retry — ask user to try again",
        }

    async def _fetch_draft(self, doc_id: str) -> dict[str, Any]:
        """Fetch the current draft body for a document."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/api/documents/{doc_id}",
                headers=self._headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                # Prefer draft_body if present, fall back to body
                draft = data.get("draft_body") or data.get("body")
                if isinstance(draft, str):
                    try:
                        draft = json.loads(draft)
                    except (json.JSONDecodeError, TypeError):
                        draft = {}
                return draft or {"type": "doc", "content": []}
        return {"type": "doc", "content": []}

    # ------------------------------------------------------------------
    # Other tools
    # ------------------------------------------------------------------

    async def _search_documents(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if "doc_type" in tool_input:
            params["doc_type"] = tool_input["doc_type"]
        if "published" in tool_input:
            params["published"] = str(tool_input["published"]).lower()
        params["limit"] = tool_input.get("limit", 10)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/api/documents",
                params=params,
                headers=self._headers,
            )
            if resp.status_code == 200:
                return {"status": "ok", "documents": resp.json()}
            return {"status": "error", "message": resp.text}

    async def _search_media(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if "query" in tool_input:
            params["q"] = tool_input["query"]
        params["limit"] = tool_input.get("limit", 10)

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/assets",
                params=params,
                headers=self._headers,
            )
            if resp.status_code == 200:
                return {"status": "ok", "assets": resp.json()}
            return {"status": "media_search_not_configured"}

    async def _get_available_doc_types(self) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/api/schema",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return {"status": "ok", "schema": resp.json()}
            return {"status": "error", "message": resp.text}

    async def _get_document_history(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        doc_id = tool_input.get("doc_id", "")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/api/documents/{doc_id}/history",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return {"status": "ok", "history": resp.json()}
            return {"status": "error", "message": resp.text}

    async def _publish_document(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        doc_id = tool_input.get("doc_id", "")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._cms_base}/api/documents/{doc_id}/publish",
                headers=self._headers,
            )
            if resp.status_code in (200, 201, 204):
                return {"status": "published", "doc_id": doc_id}
            return {"status": "error", "message": resp.text}

    async def _create_document(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._cms_base}/api/documents",
                json=tool_input,
                headers=self._headers,
            )
            if resp.status_code in (200, 201):
                return {"status": "created", "document": resp.json()}
            return {"status": "error", "message": resp.text}

    async def _add_to_changeset(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        changeset_id = tool_input.get("changeset_id")
        if changeset_id:
            url = f"{self._cms_base}/api/changesets/{changeset_id}/documents"
        else:
            url = f"{self._cms_base}/api/changesets"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                json=tool_input,
                headers=self._headers,
            )
            if resp.status_code in (200, 201):
                return {"status": "ok", "result": resp.json()}
            return {"status": "error", "message": resp.text}
