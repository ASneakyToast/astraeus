"""
Chat tool dispatcher.

Implements the curated AI tool suite scoped to the editing session.
Tools are thin wrappers over the existing CMS and mediakit HTTP APIs
plus the ProseMirror collab WebSocket for edit operations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx


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

        :param tool_name: Tool name (matches a tool registered in ``make_tools``).
        :param tool_input: Tool input dict from the LLM.
        :param context: Session context — may contain ``doc_id``, ``version``,
            ``draft_body``, ``selection``.
        :returns: Result dict forwarded back to the LLM as a tool result.
        """
        if tool_name == "edit_document":
            doc_id = tool_input.get("doc_id") or (context or {}).get("doc_id")
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
            return await self._create_document(tool_input, context)

        elif tool_name == "update_document":
            return await self._update_document(tool_input, context)

        elif tool_name == "create_changeset":
            return await self._create_changeset(tool_input)

        elif tool_name == "list_changesets":
            return await self._list_changesets()

        elif tool_name == "link_doc_to_changeset":
            return await self._link_doc_to_changeset(tool_input, context)

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

        current_draft = (context or {}).get("draft_body") or await self._fetch_draft(doc_id)
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
                await self._auto_link_changeset(doc_id, context)
                return {
                    "status": "accepted",
                    "step_count": len(steps),
                    "edit_rationale": edit_rationale,
                    "doc_id": doc_id,
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

    async def _update_document(
        self, tool_input: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        doc_id = tool_input.get("doc_id")
        if not doc_id:
            return {"status": "error", "message": "doc_id is required"}
        body = tool_input.get("body", {})
        slug = tool_input.get("slug")
        payload: dict[str, Any] = {"body": body}
        if slug:
            payload["slug"] = slug
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self._cms_base}/api/documents/{doc_id}",
                json=payload,
                headers=self._headers,
            )
            if resp.status_code == 200:
                result: dict[str, Any] = {"status": "updated", "document": resp.json()}
                await self._auto_link_changeset(doc_id, context)
                return result
            return {"status": "error", "message": resp.text}

    async def _create_document(
        self, tool_input: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._cms_base}/api/documents",
                json=tool_input,
                headers=self._headers,
            )
            if resp.status_code in (200, 201):
                new_doc = resp.json()
                result: dict[str, Any] = {"status": "created", "document": new_doc}
                if new_doc_id := new_doc.get("id"):
                    await self._auto_link_changeset(new_doc_id, context)
                return result
            return {"status": "error", "message": resp.text}

    # ------------------------------------------------------------------
    # Changeset tools
    # ------------------------------------------------------------------

    async def _auto_link_changeset(
        self, doc_id: str, context: dict[str, Any] | None
    ) -> None:
        """Link a doc to the active changeset, creating one if needed."""
        ctx = context or {}
        active_cs_id = ctx.get("active_changeset_id")

        if active_cs_id:
            try:
                await self._link_doc_to_changeset(
                    {"changeset_id": active_cs_id, "doc_id": doc_id}, context
                )
            except Exception:
                pass
            return

        # No active changeset — auto-create one
        try:
            today = datetime.now(UTC)
            auto_title = today.strftime("%b %-d")
            result = await self._create_changeset({"title": auto_title})
            if result.get("status") == "created":
                new_cs = result["changeset"]
                new_cs_id = new_cs["id"]
                ctx["active_changeset_id"] = new_cs_id
                await self._link_doc_to_changeset(
                    {"changeset_id": new_cs_id, "doc_id": doc_id}, context
                )
        except Exception:
            pass

    async def _create_changeset(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        title = tool_input.get("title", "")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._cms_base}/api/changesets",
                json={"title": title},
                headers=self._headers,
            )
            if resp.status_code in (200, 201):
                return {"status": "created", "changeset": resp.json()}
            return {"status": "error", "message": resp.text}

    async def _list_changesets(self) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._cms_base}/api/changesets?status=open",
                headers=self._headers,
            )
            if resp.status_code == 200:
                return {"status": "ok", "changesets": resp.json().get("changesets", [])}
            return {"status": "error", "message": resp.text}

    async def _link_doc_to_changeset(
        self, tool_input: dict[str, Any], context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        changeset_id = tool_input.get("changeset_id") or (context or {}).get(
            "active_changeset_id"
        )
        doc_id = tool_input.get("doc_id") or (context or {}).get("doc_id")
        if not changeset_id:
            return {"status": "error", "message": "changeset_id required"}
        if not doc_id:
            return {"status": "error", "message": "doc_id required"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._cms_base}/api/changesets/{changeset_id}/documents/{doc_id}",
                headers=self._headers,
            )
            if resp.status_code in (200, 201, 204):
                return {
                    "status": "linked",
                    "changeset_id": changeset_id,
                    "doc_id": doc_id,
                }
            return {"status": "error", "message": resp.text}


# ---------------------------------------------------------------------------
# LangChain tool factory
# ---------------------------------------------------------------------------


def make_tools(dispatcher: ToolDispatcher, context: dict[str, Any]) -> list:
    """Return a list of LangChain tools backed by *dispatcher*.

    Each tool closes over *context* (the session's ``doc_id``, ``version``,
    ``draft_body``, etc.) so callers don't need to thread it through every
    call.  The underlying :class:`ToolDispatcher` methods are unchanged.

    :param dispatcher: Configured dispatcher for this session.
    :param context: Session context dict forwarded to each dispatcher call.
    :returns: List of LangChain ``BaseTool`` instances ready for
        ``model.bind_tools()``.
    """
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    async def edit_document(
        markdown_content: str,
        edit_rationale: str,
        scope: str = "full",
    ) -> dict:
        """Apply edits to the document being edited. Write changes as Markdown."""
        return await dispatcher.dispatch(
            "edit_document",
            {
                "markdown_content": markdown_content,
                "edit_rationale": edit_rationale,
                "scope": scope,
            },
            context,
        )

    @lc_tool
    async def search_documents(
        doc_type: str = "",
        published: bool | None = None,
        limit: int = 10,
    ) -> dict:
        """Find existing CMS documents by type or content."""
        tool_input: dict[str, Any] = {"limit": limit}
        if doc_type:
            tool_input["doc_type"] = doc_type
        if published is not None:
            tool_input["published"] = published
        return await dispatcher.dispatch("search_documents", tool_input, context)

    @lc_tool
    async def publish_document(doc_id: str) -> dict:
        """Publish a document. This triggers a site rebuild."""
        return await dispatcher.dispatch(
            "publish_document", {"doc_id": doc_id}, context
        )

    @lc_tool
    async def get_available_doc_types() -> dict:
        """List all CMS document types and their fields."""
        return await dispatcher.dispatch("get_available_doc_types", {}, context)

    @lc_tool
    async def update_document(doc_id: str, body: dict, slug: str = "") -> dict:
        """Update fields on an existing CMS document. Use for structured docs (experience, projects, etc.) where fields like company, title, start_date need to be set directly. Do NOT use edit_document for these — that tool is only for rich_text prose fields."""
        tool_input: dict[str, Any] = {"doc_id": doc_id, "body": body}
        if slug:
            tool_input["slug"] = slug
        return await dispatcher.dispatch("update_document", tool_input, context)

    @lc_tool
    async def create_document(doc_type: str, body: dict, slug: str) -> dict:
        """Create a new CMS document."""
        return await dispatcher.dispatch(
            "create_document",
            {"doc_type": doc_type, "body": body, "slug": slug},
            context,
        )

    @lc_tool
    async def create_changeset(title: str = "") -> dict:
        """Create a new changeset for grouping document edits for atomic publish."""
        return await dispatcher.dispatch("create_changeset", {"title": title}, context)

    @lc_tool
    async def list_changesets() -> dict:
        """List all currently open changesets."""
        return await dispatcher.dispatch("list_changesets", {}, context)

    @lc_tool
    async def link_doc_to_changeset(
        changeset_id: str = "", doc_id: str = ""
    ) -> dict:
        """Add a document to a changeset. Falls back to the active changeset from context if changeset_id is omitted."""
        return await dispatcher.dispatch(
            "link_doc_to_changeset",
            {"changeset_id": changeset_id, "doc_id": doc_id},
            context,
        )

    return [
        edit_document,
        update_document,
        search_documents,
        publish_document,
        get_available_doc_types,
        create_document,
        create_changeset,
        list_changesets,
        link_doc_to_changeset,
    ]
