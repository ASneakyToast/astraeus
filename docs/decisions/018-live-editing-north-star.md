# ADR 018 — Live Editing North Star: Inline Edit Mode + Collaborative Step Authority

**Status:** Accepted  
**Date:** 2026-07-05

---

## Context

Astraeus was designed from the start with ProseMirror as the rich text substrate. ProseMirror's
step model — every edit is a discrete, serializable, reversible transformation — is uniquely
suited to collaborative live editing backed by a server authority. This ADR captures the
decision to build toward that north star as the primary authoring UX, making the existing
3-panel admin SPA a fallback rather than the primary interface.

The primary use case is joellithgow.com: a static Astro site where Joel (and potentially
collaborators) edit content inline on the published pages, with changes streaming live to the
CMS backend and Netlify rebuilds only triggered on explicit publish.

---

## Decision

### 1. Draft/published dual state

`CMSDocument` gains a `draft_body` column (nullable JSON). The semantics:

- `body` — the published snapshot. Written only by the publish action. Never touched by edits.
- `draft_body` — the live working copy. Written by every PATCH/step. Null if no unpublished edits.
- `GET /api/documents/{id}?draft=true` returns `draft_body ?? body` (draft if exists, else published)
- `POST /api/documents/{id}/publish` copies `draft_body → body`, clears `draft_body`, fires webhook
- `POST /api/documents/{id}/discard-draft` resets `draft_body = null`

### 2. WebSocket step authority

The CMS gains a WebSocket endpoint at `/api/documents/{id}/collab`. This is the ProseMirror
collaborative editing authority. Protocol:

- **On connect**: sends `{ type: "init", body: <draft_body>, version: <int> }`
- **From client**: `{ type: "steps", steps: [...], clientID: str, version: int }`
- **Server**: validates each step, applies to `draft_body`, increments version, persists to
  `cms_steps` table, broadcasts `{ type: "steps", steps: [...], clientIDs: [...], version: int }`
  to all connected clients
- **On version mismatch**: server sends `{ type: "reject", version: int }` — client rebases
  its pending steps against the new version

### 3. Step history

`cms_steps` table stores every step. This enables:
- Full rewind to any point between publishes
- Audit trail of who changed what and when
- `GET /api/documents/{id}/history` — list of step checkpoints with timestamps
- `GET /api/documents/{id}/history/{version}` — reconstruct body at that version

### 4. Changesets

`cms_changesets` table groups documents for atomic publish. Semantics:

- A changeset is a named collection of documents with their pending drafts
- `POST /api/changesets/{id}/publish` atomically publishes all member documents in a transaction
- Fires one `changeset.published` webhook (not N individual `document.published` events)
- Netlify (or any webhook consumer) rebuilds once, fetches all newly-published content together
- `POST /api/changesets/{id}/schedule` sets a `publish_at` timestamp; a cron job handles execution

### 5. Session auth for edit mode

The CMS gains form-based session authentication separate from the existing API key auth:
- `GET/POST /cms/auth/login` — login form, sets `cms_session` httponly cookie on success
- `GET /cms/auth/logout` — clears cookie
- `GET /cms/auth/me` — returns `{ authenticated: bool }` — callable from frontend JS without CORS issues
- Session tokens are cryptographically signed (HMAC-SHA256), short-lived (24h), stored httponly

The existing `Authorization: Bearer` API key auth is unchanged for programmatic clients (MCP,
gateways, agent tools).

### 6. Embed script

`starlette-editor` builds a second bundle: `embed.js`. This is a lightweight (~150KB target)
vanilla JS script that:
- Loads on any page where the Astro layout includes `<script src="{CMS_BASE}/editor/embed.js">`
- Calls `GET /cms/auth/me` on load — if not authenticated, does nothing (zero impact on visitors)
- If authenticated: injects a floating toolbar (non-intrusive, bottom-right corner)
- Toolbar shows document title, edit state, "Edit draft" / "Save draft" / "Publish" / "Add to changeset" actions
- On "Edit draft": fetches draft body, replaces static content in marked regions, mounts ProseMirror on rich text regions, opens metadata side panel for structured fields
- On every edit: steps stream to the WS authority — no explicit save needed
- Changeset panel: shows all dirty documents across tabs, publish all together

### 7. Framework-agnostic data attribute contract

Astro (or any static site) marks editable regions with data attributes:

```html
<article
  data-cms-id="{document_id}"
  data-cms-type="{block_type}"
  data-cms-base="{CMS_BASE}"
>
  <h1 data-cms-field="title">{title}</h1>
  <div data-cms-field="body">{rendered_body_html}</div>
</article>
```

The embed script reads these attributes. No framework-specific code. Works on Astro, plain
HTML, Next.js static export, or any other SSG.

---

## Rationale

**Why inline edit mode over admin-only editing?**  
The authoring experience of editing your own site inline — seeing the real layout, real
typography, real context — is qualitatively better than a 3-panel admin form. ProseMirror
was specifically chosen because it supports this model. The existing admin SPA is valuable
as a fallback for bulk operations and content types without a frontend representation, but
it should not be the primary interface.

**Why WebSocket steps instead of REST PATCH?**  
REST PATCH is sufficient for single-user save-on-blur. The step model is required for:
- Collaborative editing (multiple users, real-time cursor positions)
- Full rewind history (every keystroke is recoverable)
- Conflict-free rebasing (no last-write-wins data loss)
- The foundation for future approval workflows (steps can be held pending review)

**Why CMS-level changesets instead of browser-side coordination?**  
A browser-side "publish all" sends N sequential publish requests, may get N Netlify builds,
and has no atomicity guarantee. CMS-level changesets ensure: one transaction, one webhook,
one rebuild, and a correct state if a partial publish fails.

**Why session auth separate from API key auth?**  
API keys are for programmatic clients (MCP server, gateways, CI scripts) — they live in env
vars and never touch a browser. Session cookies are for human browser sessions — they must
be httponly (not readable by JS) and have different expiry semantics. Conflating the two
creates security problems in both directions.

**Why `cmsBase` injected via Astro env var?**  
The CMS backend URL is deployment-specific. Hardcoding it in `embed.js` would require
rebuilding the bundle per deployment. The Astro build injects `PUBLIC_CMS_BASE` at build
time; the layout template uses it to set `src` on the embed script tag and `data-cms-base`
on content elements.

---

## Security considerations

- `cms_session` cookie: `httponly=True`, `secure=True` (HTTPS only), `samesite="lax"`
- Session tokens: HMAC-SHA256 signed with a `SESSION_SECRET` env var; never stored in DB (stateless)
- `GET /cms/auth/me` response includes `Cache-Control: no-store` — not cacheable
- The embed script makes no mutating requests without a valid session cookie — visitors without
  a session see zero UI change
- CSRF protection on all mutating endpoints when called with session auth (double-submit cookie
  pattern or `Origin` header check)
- The CMS is deployed behind nginx on EC2 with SSL termination; the embed script `src` uses the
  HTTPS URL

---

## What the existing admin SPA becomes

The 3-panel admin (`/editor/shell`) is retained as a **fallback authoring tool**:
- Useful for content types with no frontend representation (e.g. singletons, data-only blocks)
- Useful for bulk operations (create 20 blog posts, reorder, delete)
- Works without the Astro site being deployed
- Provides a recovery path when the inline editor can't render a field (e.g. complex nested blocks)

It is no longer the primary interface. It shares the `ProseMirrorBridge` and schema endpoint
with the inline editor — they are peers on the same CMS API.

---

## Consequences

- `CMSDocument` gains `draft_body` — migration required
- `cms_steps`, `cms_changesets`, `cms_changeset_documents` are new tables
- WS endpoint requires the CMS to run in a process that supports long-lived connections
  (Uvicorn with `--workers 1` or a process manager that pins WS connections)
- `starlette-editor` gains a second build target (`embed.js`) and new modules
- Astro site requires `PUBLIC_CMS_BASE` env var and layout changes to include the embed script
- The `prosemirror-collab` npm package becomes a dependency of `starlette-editor`
