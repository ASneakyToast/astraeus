# Collaborative AI Chat — Implementation Plan

**ADR:** [ADR 019](../decisions/019-collaborative-ai-chat.md)  
**Branch base:** `feat/ns-editor-integration` → new branch `feat/collaborative-chat`  
**Status:** Ready for implementation  
**Date written:** 2026-07-05

---

## Overview

This plan implements `starlette-chat` — a new package that adds a governed, real-time AI chat
collaborator to the Astraeus editing experience. The AI participates in the same ProseMirror
WebSocket collab layer as human editors: its edits appear live in every connected browser, with
cursor attribution, undo support, and full step history.

The plan spans four packages and the `editor_src/embed/` frontend bundle. It is organized into
six phases with clear dependency gates.

---

## Dependency Graph

```
Phase CH-1 (block types + package scaffold)  ─────────────────────────────────────┐
Phase CH-2 (Python PM builder + differ)      ─── depends on CH-1 ─────────────────┤
Phase CH-3 (starlette-chat backend + WS)     ─── depends on CH-1 + CH-2 ──────────┤
                                                                                    ▼
Phase CH-4A (ChatPanel JS module)            ─── depends on CH-3 ────────────────▶ Phase CH-5 (wiring + integration)
Phase CH-4B (collab WS peer extension)       ─── depends on NS branch complete ───▶ depends on 4A + 4B
                                                                                    │
                                                                                    ▼
Phase CH-6 (tests + docs)                    ─── depends on CH-5
```

**Parallel starts:**
- CH-1 starts immediately
- CH-2 can start as soon as CH-1 scaffold exists (no CMS dependency)
- CH-3 depends on CH-1 + CH-2 only
- CH-4A and CH-4B can run in parallel once CH-3 is stable

---

## Phase CH-1 — Package Scaffold + Block Types

**Package:** new `starlette-chat`, plus `starlette-cms` (new block registrations)  
**Complexity:** Low  
**Blocks:** All subsequent phases

### Goal

Create the `starlette-chat` package skeleton and register the four new CMS block types.
No business logic yet — just structure and schema.

### Tasks

#### CH-1-1: UV workspace — add `starlette-chat` package

Create `packages/starlette-chat/` with `src/` layout:

```
packages/starlette-chat/
├── pyproject.toml
├── README.md
├── CLAUDE.md
└── src/
    └── starlette_chat/
        ├── __init__.py          # exports: ChatAPI, register_blocks()
        ├── blocks.py            # all four block definitions
        ├── app.py               # stub ChatAPI class
        ├── routes.py            # stub
        ├── session.py           # stub
        ├── streaming.py         # stub
        ├── prosemirror.py       # stub (Phase CH-2)
        ├── diff.py              # stub (Phase CH-2)
        ├── tools.py             # stub (Phase CH-3)
        └── providers/
            ├── __init__.py
            ├── base.py          # BaseProvider ABC
            └── anthropic.py     # stub AnthropicProvider
```

`pyproject.toml` dependencies:
```toml
[project]
name = "starlette-chat"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "starlette-cms>=0.5.0",
    "starlette>=0.40",
    "httpx>=0.27",
    "structlog>=24.0",
    "mistune>=3.0",              # markdown parser for Python PM builder
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.34"]
full      = ["starlette-chat[anthropic]"]
dev       = ["pytest>=8.0", "pytest-asyncio>=0.23", "httpx>=0.27"]

[tool.uv.sources]
starlette-cms = { workspace = true }
```

Add to workspace root `pyproject.toml`:
```toml
[tool.uv.workspace]
members = [
    # ... existing ...
    "packages/starlette-chat",
]
```

#### CH-1-2: Block definitions in `blocks.py`

Four block classes using existing field types. See ADR 019 API shape section for full definitions.
Key constraints:
- `ChatMessage`: `append_only=True`, `session_ref` has `on_delete="cascade"`
- `ChatSession`: NOT append_only, published immediately on creation in `routes.py`
- `SystemPrompt` and `ModelConfig`: NOT singleton at the block level (multiple personas)
  — uniqueness enforced at application layer when creating via `routes.py`

#### CH-1-3: `register_blocks(cms)` helper in `__init__.py`

```python
def register_blocks(cms: CMS) -> None:
    """Register all starlette-chat block types with a CMS instance."""
    cms.register_block(SystemPromptBlock)
    cms.register_block(ModelConfigBlock)
    cms.register_block(ChatSessionBlock)
    cms.register_block(ChatMessageBlock)
```

This is called by the host app, not inside `ChatAPI.__init__`, so blocks can be registered
before `cms.app` is accessed. Follows the same pattern as gateways.

#### CH-1-4: `BaseProvider` ABC in `providers/base.py`

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

@dataclass
class StreamEvent:
    type: str      # "thinking" | "token" | "tool_use" | "tool_result" | "done"
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
```

#### CH-1-5: Tests — block registration smoke tests

- Register all four blocks on a test CMS instance
- Assert each appears in `cms.registry.list_types()`
- Assert `ChatMessage` is `append_only`
- Assert PATCH on a ChatMessage document returns 405

---

## Phase CH-2 — Python ProseMirror Builder + Differ

**Package:** `starlette-chat`  
**Complexity:** Medium-High  
**Blocks:** Phase CH-3

### Goal

Parse markdown into a ProseMirror document dict, then diff it against a current `draft_body`
to produce the minimal set of replace steps needed to transition from one to the other.
No WS connections, no LLM — pure Python, fully testable in isolation.

### Tasks

#### CH-2-1: Markdown parser → PM doc builder (`prosemirror.py`)

Use `mistune` (AST mode) to walk a markdown string and emit ProseMirror JSON.

Supported node types (matches starlette-editor schema exactly):

| Markdown | PM node |
|---|---|
| paragraph | `paragraph` + `text` nodes |
| `# Heading` | `heading` with `level` attr |
| `**bold**` | `text` + `bold` mark |
| `_italic_` | `text` + `italic` mark |
| `` `code` `` | `text` + `code` mark |
| ```` ```lang\n...\n``` ```` | `code_block` with `params` attr |
| `> blockquote` | `blockquote` |
| `- item` | `bullet_list` → `list_item` → `paragraph` |
| `1. item` | `ordered_list` → `list_item` → `paragraph` |
| `![alt](url)` | `image` with `src`, `alt`, `title` attrs |
| `\n` (hard break) | `hard_break` |

Public API:
```python
def markdown_to_pm(text: str) -> dict:
    """Parse markdown text into a ProseMirror document dict."""

def pm_to_text(doc: dict) -> str:
    """Extract plain text from a ProseMirror document dict (for LLM context)."""
```

Unknown node types from the mistune AST that don't map to supported PM nodes are wrapped in a
`paragraph` containing the raw text, never silently dropped.

#### CH-2-2: Doc differ → replace steps (`diff.py`)

Given a current doc and a new doc, produce a list of ProseMirror step dicts that transforms
current → new. The differ operates at paragraph/block granularity, not character granularity —
this keeps step count low and avoids OT conflicts with concurrent character-level human edits.

Strategy:
1. Flatten both docs to a list of top-level block nodes (paragraphs, headings, etc.)
2. Diff the two lists using `difflib.SequenceMatcher`
3. For each changed block range: emit a `ReplaceStep` that replaces the span in the current doc
   with the new blocks

```python
def diff_docs(current: dict, new: dict) -> list[dict]:
    """
    Return a list of ProseMirror ReplaceStep dicts that transforms current → new.
    Steps are at block granularity — no character-level diffing.
    """
```

A `ReplaceStep` dict follows the ProseMirror wire format:
```json
{
  "stepType": "replace",
  "from": 5,
  "to": 42,
  "slice": { "content": [ { "type": "paragraph", "content": [...] } ] }
}
```

Position calculation: iterate `current.content`, accumulate positions accounting for node size
(1 opening token + content tokens + 1 closing token).

#### CH-2-3: Tests — builder and differ

Builder tests (unit, no CMS needed):
- Round-trip: markdown → PM → `pm_to_text()` preserves content
- Each supported node type renders correctly
- Unknown node types don't raise, produce fallback paragraph
- Empty string produces `{"type": "doc", "content": []}`

Differ tests:
- No-op diff (identical docs) → empty step list
- Single paragraph replacement → one `ReplaceStep`
- Appended paragraph → one `ReplaceStep` at end
- Deleted paragraph → one `ReplaceStep` removing it
- Multi-block mixed changes → minimal step set
- Positions are valid (from < to, within doc bounds)

---

## Phase CH-3 — `starlette-chat` Backend + WebSocket

**Package:** `starlette-chat`  
**Complexity:** High  
**Blocks:** Phase CH-4A, CH-4B (partially), CH-5

### Goal

Mountable Starlette sub-app with:
1. HTTP endpoint to create/get chat sessions
2. WebSocket endpoint for streaming chat turns
3. `AnthropicProvider` that streams tokens and dispatches tool calls
4. `edit_document` tool that submits PM steps via the collab WS

### Tasks

#### CH-3-1: `ChatAPI` class (`app.py`)

```python
class ChatAPI:
    def __init__(
        self,
        cms_base_url: str,
        cms_api_key: str,
        provider: BaseProvider | None = None,
    ) -> None: ...

    @property
    def app(self) -> Starlette: ...    # lazy, like CMS
```

`ChatAPI` holds:
- `self._cms_base` — HTTP base URL for CMS API calls
- `self._cms_api_key` — for auth headers
- `self._provider` — defaults to `AnthropicProvider()` if `anthropic` extra installed
- `self._sessions: dict[str, asyncio.Task]` — active WS sessions (GC'd on disconnect)

#### CH-3-2: Routes (`routes.py`)

```
POST   /api/chat/sessions              create session (returns session_id)
GET    /api/chat/sessions/{id}         get session + message history
WS     /api/chat/sessions/{id}/ws      streaming chat WS
```

Session creation (`POST /api/chat/sessions`):
1. Resolve `ModelConfig` and `SystemPrompt` for the requested persona
2. Create a `ChatSession` document via CMS API, publish immediately
3. Return `{ session_id, doc_id }`

Chat WS (`WS /api/chat/sessions/{id}/ws`):
1. Validate session cookie or `?api_key=` (mirrors collab WS auth)
2. On `{"type": "message"}` from client:
   a. Load `SystemPrompt` content and `ModelConfig` params
   b. Build message history from `ChatMessage` documents for this session
   c. Stream from `provider.stream(messages, system_prompt, tools, ...)`
   d. Forward all `StreamEvent`s to the browser WS
   e. On `tool_use` events: dispatch to `_handle_tool(tool_name, input, context)`
   f. Persist user + assistant `ChatMessage` records on completion

#### CH-3-3: Tool dispatcher (`tools.py`)

```python
class ToolDispatcher:
    def __init__(self, cms_base: str, api_key: str, collab_ws_base: str) -> None: ...

    async def dispatch(
        self, tool_name: str, tool_input: dict, context: dict
    ) -> dict:  # returns tool result for LLM
        ...
```

Tool routing:
- `edit_document` → `_edit_document()` (collab WS)
- `insert_media` → `_insert_media()` (collab WS)
- `search_documents` → `GET /api/documents`
- `search_media` → `GET /assets`
- `get_available_doc_types` → `GET /api/schema`
- `get_document_history` → `GET /api/documents/{id}/history`
- `publish_document` → `POST /api/documents/{id}/publish`
- `add_to_changeset` → `POST /api/changesets` or `POST /api/changesets/{id}/documents`
- `create_document` → `POST /api/documents`

#### CH-3-4: `_edit_document()` — collab WS submission

```python
async def _edit_document(
    self,
    doc_id: str,
    markdown_content: str,
    edit_rationale: str,
    context: dict,        # has version + draft_body from browser
) -> dict:
    # 1. Parse markdown → PM doc
    new_doc = markdown_to_pm(markdown_content)
    # 2. Diff against context["draft_body"]
    steps = diff_docs(context["draft_body"], new_doc)
    if not steps:
        return {"status": "no_change"}
    # 3. Connect to collab WS as "claude-assistant"
    async with _collab_ws(self._collab_base, doc_id, self._api_key) as ws:
        init = await ws.recv_json()
        assert init["type"] == "init"
        server_version = init["version"]
        # 4. Submit steps
        await ws.send_json({
            "type": "steps",
            "steps": steps,
            "clientID": "claude-assistant",
            "version": server_version,
            "doc": new_doc,
        })
        result = await ws.recv_json()
    return {
        "status": "accepted" if result["type"] == "steps" else "rejected",
        "step_count": len(steps),
        "edit_rationale": edit_rationale,
    }
```

If rejected (version conflict): fetch current draft_body, re-diff, retry once. If still rejected,
return `{"status": "conflict"}` — the LLM will narrate this to the user.

#### CH-3-5: `AnthropicProvider` (`providers/anthropic.py`)

Uses `anthropic` SDK streaming (`client.messages.stream()`). Emits `StreamEvent` for each
`content_block_delta`, `tool_use`, and `message_stop`. Handles `tool_use` blocks by emitting
`tool_use` event then `tool_result` event after dispatch. Maps Anthropic tool schema format to
the `tools.py` definitions.

#### CH-3-6: Tests

- Session creation creates a `ChatSession` document via mocked CMS HTTP API
- WS turn: mock provider emits tokens → client receives them in order
- `_edit_document`: mock collab WS accepts steps → broadcasts → returns "accepted"
- `_edit_document`: version conflict on first attempt, success on retry
- `_edit_document`: no-op diff returns "no_change" without opening WS
- All tool dispatches: happy path + error handling (404, 500 from CMS)

---

## Phase CH-4A — `ChatPanel` JavaScript Module

**Package:** `starlette-editor`  
**Complexity:** Medium  
**Blocks:** Phase CH-5

### Goal

Add `chat-panel.js` to `editor_src/embed/`. Follows `changeset-panel.js` exactly in structure:
imperative DOM, Catppuccin Mocha theme, fixed-position, no framework.

### Tasks

#### CH-4A-1: `chat-panel.js`

Public interface:
```javascript
export class ChatPanel {
  constructor(cmsBase, session, { getDocContext, collabConnection }) { ... }
  mount()   // append to document.body, hidden
  toggle()  // show/hide, init WS session on first open
  get isOpen() { ... }
}
```

Internal state machine: `idle | thinking | streaming | tool_calling | applying_edits`

Key behaviours:
- `_ensureSession()` — lazy: POST `/api/chat/sessions`, then open WS
- `send(content)` — sends `{"type":"message", content, context: getDocContext()}`
- `_onServerMessage(msg)` — routes to state handlers below
- `_appendMessage({ role, content })` — adds bubble to message list
- `_appendStreamingToken(delta)` — streams into current assistant bubble
- `_appendToolChip(tool, input)` — shows `🔍 search_documents { query: "..." }`
- `_updateToolChip(tool, summary)` — replaces chip content with result summary + ✓
- `_appendEditNotice(msg)` — shows `✏️ Applying N edits — "Punchier opener"`
  note: actual doc update arrives via the collab WS, not this panel

Layout (fixed, bottom-left, `left: 24px`, `bottom: 80px`, `width: 360px`, `max-height: 480px`):
```
┌─ Chat ──────────────────── × ─┐
│  [message bubble — user]      │
│  [message bubble — assistant] │
│  [tool chip — ✓ resolved]     │
│  [edit notice]                │
│  ─────────────────────────    │
│  [input textarea] [Send ▶]    │
└───────────────────────────────┘
```

#### CH-4A-2: Wire into `index.js`

```javascript
// index.js additions
import { ChatPanel } from './chat-panel.js'

// after toolbar + changesetPanel init:
const chatPanel = new ChatPanel(CMS_BASE, session, {
  getDocContext: () => ({
    doc_id: currentDocId,
    version: collab?.currentVersion() ?? 0,
    draft_body: collab?.currentDoc() ?? null,
    selection: collab?.currentSelection() ?? null,
  }),
  collabConnection: collab,
})
chatPanel.mount()

toolbar.setChatPanel(chatPanel)    // toolbar shows 💬 button
```

#### CH-4A-3: Toolbar extension — chat button

Add `💬` button to `toolbar.js` alongside the existing `≡ Changesets` button. Calls
`chatPanel.toggle()` on click. Shows unread indicator dot when a message arrives while panel is
closed (bump `this._unread` counter, clear on open).

#### CH-4A-4: Tests (`__tests__/chat-panel.test.js`)

Using Vitest + jsdom:
- Mount creates DOM elements, initially hidden
- `toggle()` shows panel, calls `getDocContext()` to init WS session
- Receiving `token` events builds streaming bubble
- Receiving `tool_use` → `tool_result` shows + resolves chip
- Receiving `applying_edits` shows edit notice
- Receiving `done` returns to idle state
- Toolbar chat button toggles panel

---

## Phase CH-4B — Collab WS Peer Extension

**Package:** `starlette-cms`  
**Complexity:** Low  
**Blocks:** Phase CH-5

### Goal

Extend the collab WS `init` message and `CollabManager` to support `client_type` and `display`
fields, so the browser toolbar can distinguish human vs. AI peers.

### Tasks

#### CH-4B-1: `CollabManager` — peer registry

Add `peer_info: dict[str, dict]` to `CollabManager`, keyed by `client_id`.

On WS connect: client may send `{"type": "presence", "display": "Joel", "client_type": "human"}`
within 2 seconds. If not received, defaults to `{"display": client_id, "client_type": "human"}`.

`starlette-chat` sends presence immediately on connect:
```json
{"type": "presence", "display": "Claude", "client_type": "ai"}
```

#### CH-4B-2: `init` message — `peers` array

When a new client connects, the `init` message they receive includes the current peer list:
```json
{
  "type": "init",
  "version": 47,
  "doc": { "..." },
  "peers": [
    { "client_id": "joel-abc", "type": "human", "display": "Joel" },
    { "client_id": "claude-assistant", "type": "ai", "display": "Claude" }
  ]
}
```

Broadcast `{"type": "peer_joined", "peer": {...}}` to existing connections when a new peer connects.
Broadcast `{"type": "peer_left", "client_id": "..."}` when a peer disconnects.

`collab.js` handles these new message types: updates `this._peers` map and calls
`toolbar.updatePeers(peers)`.

#### CH-4B-3: `toolbar.js` — peer presence display

```javascript
updatePeers(peers) {
  // render ●Joel ●Sarah ◆Claude in toolbar
  // ● for type:"human", ◆ for type:"ai"
  // pulse ◆ when AI peer sends {"type":"editing"} message
}
```

`starlette-chat` sends `{"type": "editing", "doc_id": "..."}` on the collab WS when it begins
submitting steps, and `{"type": "editing_done"}` when the accepted steps are broadcast. The
toolbar pulses the `◆` during this window.

#### CH-4B-4: Tests

- `CollabManager` peer registry: presence registered, broadcast on join/leave
- `init` message contains correct `peers` array
- `peer_joined` / `peer_left` broadcasts arrive at existing connections
- `toolbar.js`: renders correct icons for human vs AI peer types
- Pulse animation triggered by `editing` / `editing_done` messages

---

## Phase CH-5 — Integration Wiring

**Package:** `starlette-chat`, `starlette-editor`, demo app  
**Complexity:** Medium  
**Blocks:** Phase CH-6

### Goal

Connect all the pieces end-to-end. Update the demo app to mount `starlette-chat`. Build and
verify the full flow: user types in chat panel → LLM streams → `edit_document` tool fires →
steps arrive in the editor.

### Tasks

#### CH-5-1: Demo app integration

Update `examples/demo/app.py`:
```python
from starlette_chat import ChatAPI, register_blocks
from starlette_chat.providers.anthropic import AnthropicProvider

register_blocks(cms)   # before cms.app is accessed

chat = ChatAPI(
    cms_base_url="http://localhost:8000/cms",
    cms_api_key=os.environ["CMS_API_KEY"],
    provider=AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"]),
)
app.mount("/chat", app=chat.app)
```

#### CH-5-2: `embed.js` — collab WS base URL for `starlette-chat`

`ChatPanel` needs the collab WS base URL (same as `CollabConnection`). Pass from `index.js`:
```javascript
const chatPanel = new ChatPanel(CMS_BASE, session, {
  collabBase: CMS_BASE.replace(/^http/, 'ws'),
  ...
})
```

#### CH-5-3: esbuild — add `chat-panel.js` to embed bundle

Update `Makefile` embed build target to include `chat-panel.js` in the bundle entry. No separate
chunk — keep it in the same `embed.js` bundle as `changeset-panel.js`.

#### CH-5-4: CORS + auth headers for chat WS

Chat WS auth mirrors collab WS: `?api_key=` query param. The session cookie from
`starlette-cms` auth is sent automatically by the browser. `starlette-chat` validates it by
calling `GET /api/auth/me` on the CMS with the cookie forwarded, or accepts `?api_key=` for
server-to-server (`starlette-chat` calling its own collab WS as claude-assistant).

#### CH-5-5: End-to-end smoke test

Manual verification checklist (to be automated in CH-6):
- [ ] Demo app starts, all packages mount correctly
- [ ] Chat panel opens, session is created, `ChatSession` document visible in CMS
- [ ] Typing a message streams tokens into the chat panel
- [ ] "Rewrite intro" prompt triggers `edit_document` tool call
- [ ] Steps appear in editor in real time (Joel's view updates)
- [ ] `CMSStep` rows in DB have `client_id = "claude-assistant"`
- [ ] `◆Claude` appears in toolbar while WS is connected
- [ ] Changeset panel correctly shows the document as having a draft
- [ ] Publish flow works end-to-end

---

## Phase CH-6 — Tests, Docs, ADR Finalization

**Package:** all  
**Complexity:** Low  
**Blocks:** none (final phase)

### Tasks

#### CH-6-1: Integration tests (`packages/starlette-chat/tests/test_integration.py`)

Using `httpx.AsyncClient` + `ASGITransport`:
- Full turn: user message → LLM response → ChatMessage records created
- `edit_document` tool: steps submitted to collab WS → broadcast → ChatMessage with `steps_applied > 0`
- Session history: GET session returns messages in order
- Auth: unauthenticated WS connect returns 403

#### CH-6-2: JS tests complete

Ensure `uv run make test-js` passes with new `chat-panel.test.js` and updated `collab.test.js`
(peer presence tests).

#### CH-6-3: Package CLAUDE.md

Write `packages/starlette-chat/CLAUDE.md` covering:
- Python PM builder scope (which node types, what to do with unknowns)
- Collab WS client pattern (`_edit_document` → steps, not REST)
- Tool dispatcher: which tools call CMS HTTP vs. collab WS
- Provider ABC contract
- The "two WS connections" note (collab + chat)

#### CH-6-4: Update roadmap and architecture docs

- Add Phase CH-1 through CH-6 to `docs/roadmap.md` completed phases table
- Update `docs/architecture.md` stack diagram to include `starlette-chat`
- Update `docs/architecture.md` package relationships section

---

## Cross-reference: what lives where

| Concern | Package | File |
|---|---|---|
| `ChatSession`, `ChatMessage`, `SystemPrompt`, `ModelConfig` blocks | `starlette-chat` | `blocks.py` |
| `register_blocks(cms)` | `starlette-chat` | `__init__.py` |
| Markdown → PM doc | `starlette-chat` | `prosemirror.py` |
| PM doc → replace steps | `starlette-chat` | `diff.py` |
| Chat WS endpoint | `starlette-chat` | `routes.py` |
| Tool dispatcher | `starlette-chat` | `tools.py` |
| Collab WS client (AI as peer) | `starlette-chat` | `tools.py:_edit_document` |
| `BaseProvider` ABC | `starlette-chat` | `providers/base.py` |
| `AnthropicProvider` | `starlette-chat` | `providers/anthropic.py` |
| Peer presence in `CollabManager` | `starlette-cms` | `collab.py` |
| `init` peers array, peer_joined/left | `starlette-cms` | `api/collab.py` |
| `ChatPanel` JS | `starlette-editor` | `editor_src/embed/chat-panel.js` |
| Toolbar peer presence + chat button | `starlette-editor` | `editor_src/embed/toolbar.js` |
| Peer handling in `CollabConnection` | `starlette-editor` | `editor_src/embed/collab.js` |
| `index.js` wiring | `starlette-editor` | `editor_src/embed/index.js` |

---

## What is explicitly out of scope for this plan

These are deferred to future ADRs / phases:

- **Multi-turn agent loops** — current plan targets single-turn tool invocations only
- **`starlette-chat` MCP server** — exposing sessions as agent-readable via MCP
- **OpenAI provider** — `BaseProvider` ABC stubs it; implementation deferred
- **Persona routing** — delivering different `SystemPrompt` / `ModelConfig` per document type or user role
- **Voice / multimodal input** — chat panel is text-only
- **Chat history search** — `ChatMessage` documents are queryable via CMS list API, but no dedicated UI
- **Collaborative chat** — multiple humans in the same chat session simultaneously
