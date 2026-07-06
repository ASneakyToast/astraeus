# ADR 019 — Collaborative AI Chat with In-Editor Editing

**Status:** Accepted  
**Date:** 2026-07-05

---

## Context

With the NS live-editing system in place (ADR 018), multiple human editors can collaborate on a
document in real time through the ProseMirror WebSocket step authority. The natural extension is
an AI collaborator that participates in the same session — not a sidebar that suggests text for
the user to copy-paste, but a first-class collab peer that submits edits directly into the live
document, visible to all connected editors simultaneously.

Three design pressures shaped this ADR:

1. **The seam problem.** If AI edits bypass the collab WS and go through a REST PATCH instead,
   Sarah's editor doesn't update in real time when Claude makes a change. Any architecture that
   splits human edits (WS) from AI edits (REST) produces a visible, confusing seam.

2. **The prompt versioning pattern.** ADR 009 (singletons) and the VPP prompt-versioning use case
   established that production prompts and model configs are governed documents — versioned,
   reviewed, auditable. The chat feature should inherit this, not invent a separate config system.

3. **The audit trail requirement.** Every AI edit should be attributable in the step history
   (`CMSStep.client_id = "claude-assistant"`) and every conversation should be a governed document
   (append-only `ChatMessage` records linked to the session and the document version at the time).

---

## Decision

### 1. `starlette-chat` is a new, independent package

`starlette-chat` is a peer of `starlette-cms` and `mediakit` — it depends on `starlette-cms`
but `starlette-cms` never imports it. It mounts independently in the host app:

```python
app.mount("/cms",   app=cms.app)
app.mount("/chat",  app=chat.app)    # starlette-chat
app.mount("/media", app=media.app)
```

It does NOT register as a `starlette-cms` extension route. Chat is not a CMS sub-feature; it is
a peer that uses the CMS as its storage and collab layer.

### 2. Chat sessions and messages are CMS documents

`ChatSession` and `ChatMessage` are registered as block types in `starlette-cms`. This gives them
full version history, audit trail, and MCP tool access for free.

`ChatMessage` uses `append_only=True` — messages are immutable records once written.
`ChatSession` is a normal mutable document — its `summary` and `title` can be updated.

Both carry `DocumentRef` fields linking to the document being edited and to the `ModelConfig` and
`SystemPrompt` singletons active at the time the session was created. This closes the lineage
loop: you can answer "which prompt version was active for the session where the user complained?"

### 3. `starlette-chat` acts as a collab WS client for edits

When Claude invokes the `edit_document` tool, `starlette-chat` does not PATCH the document via
REST. Instead it:

1. Opens a WebSocket connection to `/api/documents/{id}/collab` with
   `client_id = "claude-assistant"`
2. Receives the current `init` message (doc + version)
3. Translates the AI-produced markdown into a ProseMirror document via a Python PM builder
4. Diffs the new doc against the current draft using a minimal replace-step algorithm
5. Submits steps with `client_version = <current version>`
6. Disconnects after the steps are confirmed

This means every human editor sees the AI's changes arrive live, with `◆Claude` cursor attribution
in the toolbar, indistinguishable in delivery from a human editor's keystrokes.

### 4. Markdown → ProseMirror steps via Python PM builder

`starlette-chat` ships a Python ProseMirror document builder (`starlette_chat/prosemirror.py`)
that covers the node types the starlette-editor schema actually uses:

- `doc`, `paragraph`, `heading` (levels 1–6)
- `text` with marks: `bold`, `italic`, `code`
- `code_block`, `blockquote`, `bullet_list`, `ordered_list`, `list_item`
- `image` (from mediakit asset keys)
- `hard_break`

A Python markdown parser (mistune or commonmark) drives the builder. The output is a ProseMirror
doc dict that can be diffed against `draft_body` to produce replace steps.

Node types not supported in this builder are passed through as opaque JSON. The builder does not
need to handle RichTextField embeds, custom blocks, or any node type not listed above.

No Node.js subprocess is required. The editor's prosemirror-markdown bundle remains browser-only.

### 5. Chat has its own WebSocket channel, separate from the collab WS

The browser opens two WS connections when the chat panel is open:

- `/api/documents/{id}/collab` — ProseMirror steps (collab.js, unchanged)
- `/api/chat/sessions/{id}/ws` — conversation turns, streaming tokens, tool events

This keeps concerns separated: the collab WS never carries conversation text, and the chat WS
never carries raw ProseMirror steps. The chat WS protocol is:

**Client → server:**
```json
{
  "type": "message",
  "content": "make the intro more punchy",
  "context": {
    "doc_id": "abc123",
    "version": 47,
    "draft_body": { "...prosemirror doc..." },
    "selection": { "from": 0, "to": 84 }
  }
}
```

**Server → client (stream):**
```json
{ "type": "thinking" }
{ "type": "token", "delta": "Sure, " }
{ "type": "tool_use", "tool": "edit_document", "input": { "..." } }
{ "type": "tool_result", "tool": "edit_document", "summary": "Applied 3 edits" }
{ "type": "applying_edits", "doc_id": "abc123", "step_count": 3,
  "edit_rationale": "Punchier opener" }
{ "type": "done", "message_id": "msg_789" }
```

The `draft_body` in the context message is the live ProseMirror doc — not the last published
version. This ensures the AI sees exactly what every human editor is looking at, including any
unsaved edits in the session.

### 6. Curated tool suite — not raw MCP passthrough

The AI receives a curated set of tools scoped to the editing session, implemented in
`starlette_chat/tools.py`. They are thin wrappers over the existing CMS and mediakit HTTP APIs,
not a separate code path:

| Chat tool | Wraps |
|---|---|
| `edit_document` | Collab WS step submission (new) |
| `insert_media` | Collab WS step submission (new) |
| `search_documents` | starlette-cms `/api/documents` |
| `search_media` | mediakit `/assets?...` |
| `get_available_doc_types` | starlette-cms `/api/schema` |
| `get_document_history` | starlette-cms `/api/documents/{id}/history` |
| `publish_document` | starlette-cms `/api/documents/{id}/publish` |
| `add_to_changeset` | starlette-cms `/api/changesets` |
| `create_document` | starlette-cms `/api/documents` |

The existing MCP servers (starlette-cms MCP, mediakit MCP) remain the correct external-agent
interface for Claude Code, Claude Desktop, and scripts. The chat tool suite is the correct
in-editor interface — same underlying CMS, different abstraction level.

### 7. AI presence in the collab toolbar

The collab WS `init` message is extended to include a `client_type` field:

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

`toolbar.js` renders `●Joel` (filled circle, human) vs `◆Claude` (diamond, AI). When
`starlette-chat` is actively submitting steps, it sends a `{"type": "editing"}` message on the
chat WS so the browser can pulse the `◆` indicator during the edit.

### 8. `ChatPanel` is a peer of `ChangesetPanel` in embed.js

A new `chat-panel.js` module is added to `editor_src/embed/`. It follows the same imperative DOM,
Catppuccin Mocha, fixed-position panel pattern as `changeset-panel.js`. It sits bottom-left;
the changeset panel remains bottom-right. Both can be open simultaneously.

The `ChatPanel` is wired in `index.js` alongside the `ChangesetPanel` and `EditToolbar`.

---

## API shape

### New package structure

```
packages/starlette-chat/
├── pyproject.toml
├── README.md
└── src/
    └── starlette_chat/
        ├── __init__.py          # ChatAPI, register_with_cms(), all block types
        ├── blocks.py            # ChatSessionBlock, ChatMessageBlock,
        │                        # SystemPromptBlock, ModelConfigBlock
        ├── app.py               # ChatAPI — mountable Starlette sub-app
        ├── routes.py            # HTTP + WS route handlers
        ├── session.py           # ChatSessionManager
        ├── streaming.py         # WS streaming helpers
        ├── prosemirror.py       # Python PM doc builder + markdown parser
        ├── diff.py              # doc → steps differ
        ├── tools.py             # curated AI tool definitions
        └── providers/
            ├── __init__.py
            ├── base.py          # BaseProvider ABC
            └── anthropic.py     # AnthropicProvider (default)
```

### Block types

```python
# ChatSession — mutable document, published immediately on creation
@block("chat_session")
class ChatSessionBlock:
    persona: str        = SelectField(choices=["default", "support", "coding", "creative"])
    user_id: str        = TextField(required=False)
    title: str          = TextField(required=False)
    doc_ref: str        = DocumentRef(block_type="*", on_delete="nullify", required=False)
    doc_version: int    = NumberField(required=False)
    model_config_ref: str = DocumentRef(block_type="model_config", on_delete="nullify")
    prompt_ref: str     = DocumentRef(block_type="system_prompt", on_delete="nullify")
    summary: str        = TextField(required=False)
    turn_count: int     = NumberField(default=0)

# ChatMessage — immutable audit record
@block("chat_message", append_only=True)
class ChatMessageBlock:
    session_ref: str    = DocumentRef(block_type="chat_session", on_delete="cascade")
    role: str           = SelectField(choices=["user", "assistant", "tool"])
    content: str        = TextField(required=True)
    turn_index: int     = NumberField(required=True)
    # tool use
    tool_name: str      = TextField(required=False)
    tool_call_id: str   = TextField(required=False)
    # telemetry (assistant messages only)
    model_used: str     = TextField(required=False)
    prompt_tokens: int  = NumberField(required=False)
    completion_tokens: int = NumberField(required=False)
    latency_ms: int     = NumberField(required=False)
    steps_applied: int  = NumberField(required=False)

# SystemPrompt — singleton per (persona) key
@block("system_prompt")
class SystemPromptBlock:
    persona: str           = SelectField(choices=["default", "support", "coding", "creative"])
    content: str           = TextField(required=True)
    change_rationale: str  = TextField(required=True)
    authored_by: str       = TextField(required=True)
    version_notes: str     = TextField(required=False)

# ModelConfig — singleton per (persona) key
@block("model_config")
class ModelConfigBlock:
    persona: str           = SelectField(choices=["default", "support", "coding", "creative"])
    provider: str          = SelectField(choices=["anthropic", "openai"], default="anthropic")
    model_name: str        = TextField(required=True)
    temperature: float     = NumberField(min_value=0.0, max_value=2.0, precision=2, default=1.0)
    max_tokens: int        = NumberField(min_value=1, max_value=32768, default=4096)
    system_prompt_ref: str = DocumentRef(block_type="system_prompt", on_delete="nullify")
```

### New CMS WS protocol extension

`collab.py` `init` message gains `peers` array. Clients may optionally send
`{"type": "presence", "display": "...", "client_type": "human|ai"}` after connecting
to register a display name. Backward-compatible: missing `peers` is treated as empty.

---

## Rationale

**AI as collab peer, not sidebar.** Submitting through the step authority means every editor
sees AI edits arrive in real time with cursor attribution. The alternative — REST PATCH — produces
a seam: Sarah's editor doesn't update until she refreshes.

**Python PM builder, not Node subprocess.** The editor's block schema is bounded and known. A
Python builder covering the actual node types in use is more self-contained than requiring Node
at runtime and cheaper to maintain than a full ProseMirror port. Unknown node types are passed
through as opaque JSON rather than failing.

**Curated tool suite.** The raw MCP tools operate at the document-CRUD level. The chat tool suite
operates at the editing-session level, where context (current draft, selection, version) is
implicit. Layering over the same HTTP APIs keeps the implementation thin.

**`SystemPrompt` and `ModelConfig` as documents, not config files.** Inherits the governance
primitives established in the VPP use cases: version history, reviewer, change rationale, webhook
cache invalidation. No new config mechanism needed.

---

## Alternatives considered

**Node subprocess for markdown → PM steps.** Rejected. Requires Node available in the Python
runtime, adds a process-management layer, and the bounded schema means a Python builder is
tractable.

**Full-doc replace step instead of diff.** Rejected. A single `replaceWith` step conflicts badly
with concurrent human edits in flight and makes undo history coarse. The differ generates surgical
steps that interleave correctly with human edits.

**Raw MCP tool passthrough in chat.** Rejected. MCP tools operate at document-CRUD level without
session context (current draft, selection, active version). The curated suite passes context
implicitly from the chat session, reducing prompt complexity and preventing out-of-band edits that
bypass the collab layer.

**REST PATCH for AI edits.** Rejected. Violates the principle that all edits flow through the
step authority. Connected human editors would not see AI edits in real time.

**`starlette-chat` as a CMS extension route.** Rejected. Chat is a peer, not a sub-feature of
the editor. Independent mounting mirrors the mediakit pattern and keeps `starlette-cms` ignorant
of the chat package.

---

## Consequences

**Positive:**
- Every AI edit is attributed in `CMSStep` history with `client_id = "claude-assistant"`
- Sarah sees Claude's rewrites arrive live, same as Joel's keystrokes
- Every conversation is a governed document — auditable, linkable, versionable
- No new config system: `SystemPrompt` and `ModelConfig` inherit all CMS governance primitives
- External MCP tools and in-editor chat coexist on the same underlying CMS with no duplication

**Negative / tradeoffs:**
- `starlette-chat` must manage a collab WS connection per edit invocation — short-lived but real
  WS overhead
- Python PM builder must be kept in sync with the editor's actual node schema; schema changes
  require a builder update
- Two WS connections in the browser (collab + chat) when the chat panel is open

**Neutral / deferred:**
- Multi-turn tool use (agent loops) — the streaming protocol supports it but the initial
  implementation targets single-turn tool invocations
- `starlette-chat` MCP server (exposing chat sessions as agent-readable documents) — deferred
- Persona routing (different `SystemPrompt` / `ModelConfig` per context) — deferred to Phase CH-3
- OpenAI provider — `BaseProvider` ABC stubs it; implementation deferred

---

## Design History

1. 2026-07-05 — Initial draft. AI-as-collab-peer architecture, Python PM builder decision,
   curated tool suite, `ChatPanel` as peer of `ChangesetPanel` in embed.js.
