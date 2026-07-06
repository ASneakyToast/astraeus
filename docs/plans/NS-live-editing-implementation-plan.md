# North Star: Live Editing — Implementation Plan

**ADR:** [ADR 018](../decisions/018-live-editing-north-star.md)  
**Branch base:** `feat/gateway-admin-ui` → new branch `feat/live-editing-north-star`  
**Status:** Ready for implementation  
**Date written:** 2026-07-05

---

## Overview

This plan implements the full live inline editing system for Astraeus. It spans four packages
(`starlette-cms`, `starlette-editor`, `starlette-cms-gateways` for cron scheduling, and the
Astro frontend `joellithgow`). Work is organized into six phases with clear dependency boundaries
so subagents can work in parallel where safe.

---

## Dependency Graph

```
Phase 1A (draft/published dual state)  ──────────────────────┐
Phase 1B (session auth)                ──────────────────────┤
Phase 1C (cms_changesets)              ──── depends on 1A ───┤
                                                              ▼
Phase 2  (WS step authority)           ──── depends on 1A ───▶  Phase 3A (embed.js split)
                                                              │         depends on 1A+1B
Phase 3B (collab client in embed)      ──── depends on 2+3A ─┤
Phase 3C (changeset UI in embed)       ──── depends on 1C+3A ┤
                                                              ▼
Phase 4  (Astro wiring)                ──── depends on 3A+1B+1C
```

**Parallel starts (no dependencies on each other):**
- Phase 1A, 1B can start immediately in parallel
- Phase 1C can start as soon as 1A is done
- Phase 2 can start as soon as 1A is done
- Phase 3A can start as soon as 1A + 1B are done

---

## Phase 1A — Draft/Published Dual State
**Package:** `starlette-cms`  
**Complexity:** Medium  
**Blocks:** Phase 1C, Phase 2, Phase 3A

### Goal
Every document can have a live working draft separate from its published snapshot. Editing
always touches the draft. Publishing copies draft → published snapshot.

### Tasks

#### 1A-1: Schema — add `draft_body` column
- Add `draft_body = JSON(null=True, required=False)` to `CMSDocument` in `tables.py`
- Add `draft_version = Integer(default=0)` to `CMSDocument` — tracks step version, incremented
  on every accepted step or PATCH
- Write migration `piccolo_migrations/2026-07-NS-draft-body.py`:
  ```sql
  ALTER TABLE cms_documents ADD COLUMN draft_body JSON;
  ALTER TABLE cms_documents ADD COLUMN draft_version INTEGER NOT NULL DEFAULT 0;
  CREATE INDEX idx_cms_documents_draft ON cms_documents (id) WHERE draft_body IS NOT NULL;
  ```
- Bump `starlette-cms` version to `0.6.0`

#### 1A-2: PATCH endpoint writes to `draft_body`
- `PATCH /api/documents/{id}` currently writes to `body`. Change: write to `draft_body` instead.
- If `draft_body` is null at PATCH time, copy current `body` into `draft_body` first
  (so the draft starts from the published state, not empty)
- Increment `draft_version` on every PATCH
- Response includes `"draft": true, "draft_version": <int>` in the document envelope

#### 1A-3: GET endpoint — draft query param
- `GET /api/documents/{id}?draft=true` → return `draft_body` if non-null, else `body`
- Response includes `"has_draft": bool` field on all document responses
- `GET /api/documents` list endpoint: add `has_draft` to each item in the list

#### 1A-4: Publish — copy draft → body
- `POST /api/documents/{id}/publish`:
  - If `draft_body` is non-null: copy to `body`, set `draft_body = null`, reset `draft_version = 0`
  - If `draft_body` is null: publish is a no-op body-wise (re-publish with same content — allowed)
  - Existing publish semantics (set `published=true`, `published_at=now`, fire webhook) unchanged

#### 1A-5: Discard draft endpoint
- `POST /api/documents/{id}/discard-draft`
  - Sets `draft_body = null`, `draft_version = 0`
  - Returns 200 with the document in its current published state
  - Auth: same as PATCH (mutating)

#### 1A-6: Tests
- `test_draft_body.py` — all cases:
  - PATCH creates draft, leaves body unchanged
  - GET without `?draft=true` returns published body
  - GET with `?draft=true` returns draft body
  - Publish copies draft → body, clears draft
  - Discard draft reverts to published state
  - List response includes `has_draft` field
  - Re-publish with no draft re-publishes same content (allowed)
  - Draft version increments on each PATCH

---

## Phase 1B — Session Auth
**Package:** `starlette-cms`  
**Complexity:** Medium  
**Blocks:** Phase 3A, Phase 4

### Goal
Browser-based login via cookie session, separate from the API key auth used by programmatic
clients. Zero impact on existing auth for MCP/gateways/agent tools.

### Tasks

#### 1B-1: Session token utilities (`starlette_cms/session.py`)
- `generate_session_token(user_id: str, secret: str) -> str`
  - Payload: `{ sub: user_id, iat: unix_ts, exp: iat + 86400 }`
  - Signed with HMAC-SHA256 using `secret`
  - Encoded as `base64url(payload).base64url(signature)` — no JWT library dependency
- `validate_session_token(token: str, secret: str) -> str | None`
  - Returns `user_id` if valid and not expired, `None` otherwise
- `SESSION_SECRET` read from `os.environ["CMS_SESSION_SECRET"]`; raises `RuntimeError` if
  session auth is used without it set

#### 1B-2: CMS constructor — session auth config
- Add to `CMS.__init__`: `session_secret: str | None = None`, `admin_users: dict[str, str] | None = None`
  - `admin_users`: `{ "joel": "bcrypt_hash" }` — simple single/multi user map
  - Alternative: `admin_auth: Callable[[str, str], bool] | None = None` for custom auth
- If `session_secret` is None and session endpoints are accessed, raise a clear error

#### 1B-3: Auth routes (`starlette_cms/api/auth.py`)
- `GET /api/auth/login` — serve the login HTML form (inline f-string, same pattern as editor shell)
  - Form: username + password, POST to same URL
  - Minimal styling, dark theme consistent with gateway admin
- `POST /api/auth/login`
  - Validates username + password against `admin_users` (bcrypt comparison)
  - On success: set `cms_session` cookie (`httponly=True, secure=True, samesite="lax"`, 24h expiry)
  - Redirect to `?next=` param or `/`
  - On failure: re-render form with error message
- `POST /api/auth/logout`
  - Clears `cms_session` cookie
  - Redirects to `/api/auth/login`
- `GET /api/auth/me`
  - Reads `cms_session` cookie, validates token
  - Returns `{ "authenticated": true/false }` — always 200
  - `Cache-Control: no-store` header

#### 1B-4: Auth helper — session check
- `check_session_auth(request: Request, cms: CMS) -> bool`
  - Reads `cms_session` cookie
  - Validates with `validate_session_token`
  - Returns `True` if valid

#### 1B-5: Tests
- `test_session_auth.py`:
  - Login with correct credentials → cookie set → 302 redirect
  - Login with wrong credentials → 200 with error form
  - `GET /api/auth/me` with valid cookie → `{ authenticated: true }`
  - `GET /api/auth/me` with no/invalid cookie → `{ authenticated: false }`
  - Logout → cookie cleared
  - Token expiry: expired token returns `authenticated: false`
  - Session secret not configured → clear error

---

## Phase 1C — Changesets
**Package:** `starlette-cms`  
**Complexity:** Medium  
**Depends on:** Phase 1A (draft_body, draft state)  
**Blocks:** Phase 3C, Phase 4

### Goal
Atomic multi-document publish. Group documents into a named changeset, publish atomically,
fire one webhook, trigger one Netlify rebuild.

### Tasks

#### 1C-1: Schema — new tables
```sql
-- cms_changesets
CREATE TABLE cms_changesets (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(500) DEFAULT '',
    status VARCHAR(16) DEFAULT 'open',  -- 'open' | 'published' | 'scheduled'
    created_at TIMESTAMPTZ,
    publish_at TIMESTAMPTZ,             -- NULL = not scheduled
    published_at TIMESTAMPTZ            -- NULL = not yet published
);

-- cms_changeset_documents  
CREATE TABLE cms_changeset_documents (
    changeset_id VARCHAR(36),
    document_id VARCHAR(36),
    added_at TIMESTAMPTZ,
    PRIMARY KEY (changeset_id, document_id)
);
```
- Migration: `piccolo_migrations/2026-07-NS-changesets.py`
- Piccolo table classes in `tables.py`: `CMSChangeset`, `CMSChangesetDocument`

#### 1C-2: Changeset CRUD API (`starlette_cms/api/changesets.py`)
- `POST /api/changesets` — create changeset `{ title?: str }`; returns changeset object
- `GET /api/changesets` — list changesets; query params: `status=open|published|scheduled`
- `GET /api/changesets/{id}` — get one, includes `documents: [{ id, type, slug, has_draft }]`
- `POST /api/changesets/{id}/documents/{doc_id}` — add document to changeset
  - 404 if document doesn't exist
  - 409 if document already in changeset
- `DELETE /api/changesets/{id}/documents/{doc_id}` — remove document from changeset
- `DELETE /api/changesets/{id}` — delete changeset (does NOT delete documents, only unpublished)

#### 1C-3: Changeset publish
- `POST /api/changesets/{id}/publish`
  - Atomic transaction: for each document in changeset:
    - Copy `draft_body → body` (if draft exists), clear `draft_body`
    - Set `published=true`, `published_at=now`
  - Set `changeset.status = "published"`, `changeset.published_at = now`
  - Fire ONE webhook: `changeset.published` with payload:
    ```json
    {
      "event": "changeset.published",
      "changeset_id": "...",
      "title": "...",
      "document_ids": ["...", "..."],
      "timestamp": "..."
    }
    ```
  - Returns the updated changeset object

#### 1C-4: Changeset scheduling
- `POST /api/changesets/{id}/schedule` — `{ publish_at: ISO8601 }`
  - Sets `changeset.status = "scheduled"`, `changeset.publish_at = publish_at`
- Background cron job (separate from the CMS request cycle):
  - `starlette_cms/scheduler.py` — `check_scheduled_changesets(cms)`
  - Queries `CMSChangeset` where `status = "scheduled"` and `publish_at <= now`
  - Calls the publish logic for each due changeset
  - Designed to be called from an external cron (e.g. `cms scheduler run` CLI command, or
    `starlette-cms-gateways` cron runner)
- `cms scheduler status` CLI — show scheduled changesets

#### 1C-5: Tests
- `test_changesets.py`:
  - Create / list / get changeset
  - Add/remove documents
  - Publish fires atomic transaction (all docs published or none)
  - Publish fires one `changeset.published` webhook (not per-document)
  - Scheduled changeset — `check_scheduled_changesets` publishes when `publish_at` is past
  - Delete changeset does not affect documents

---

## Phase 2 — WebSocket Step Authority
**Package:** `starlette-cms`  
**Complexity:** High  
**Depends on:** Phase 1A  
**Blocks:** Phase 3B

### Goal
ProseMirror collaborative editing server. Validates and applies steps, persists history,
broadcasts to all connected clients. Correct implementation of the `prosemirror-collab`
server protocol.

### Tasks

#### 2-1: Schema — cms_steps table
```sql
CREATE TABLE cms_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id VARCHAR(36) NOT NULL,
    client_id VARCHAR(36) NOT NULL,
    version INTEGER NOT NULL,    -- version AFTER this step is applied
    step_data TEXT NOT NULL,     -- JSON-serialized ProseMirror step
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_cms_steps_doc_version ON cms_steps (document_id, version);
```
- Migration: `piccolo_migrations/2026-07-NS-steps.py`
- Piccolo table class `CMSStep` in `tables.py`

#### 2-2: Step authority logic (`starlette_cms/collab.py`)
- `CollabAuthority` class — manages the authoritative state for one document:
  - `__init__(document_id, draft_body, version)`
  - `apply_steps(steps: list[dict], client_id: str, client_version: int) -> CollabResult`
    - If `client_version != self.version`: return `CollabResult(rejected=True, version=self.version)`
    - For each step: apply to current `draft_body` using `apply_step(doc, step)` (pure Python
      ProseMirror step application — see note below)
    - If all steps valid: increment version, update `draft_body`
    - Persist steps to `cms_steps` in one batch insert
    - Update `CMSDocument.draft_body` and `draft_version`
    - Return `CollabResult(accepted=True, steps=steps, version=self.version)`

**Note on Python step application:** ProseMirror step application is normally done in JS.
For server-side validation we have two options:
  1. Implement a Python subset of ProseMirror's `applyStep` for the node types we use
  2. Trust client steps structurally (validate JSON schema only) and store them; reconstruct
     the document in JS when needed

  **Decision:** Start with option 2 (structural validation only). The server validates that
  each step is well-formed JSON with the expected `stepType` field, then stores it. The
  server rebuilds the `draft_body` by applying all steps in version order when a client
  connects. A pure-Python step applier is deferred as a future hardening task.

- `CollabManager` class — manages authorities for all connected documents:
  - `get_authority(document_id) -> CollabAuthority` — creates or returns existing
  - `authority_for(document_id)` — context manager, acquires per-document asyncio.Lock
  - Garbage collects unused authorities after 5 minutes of no connections

#### 2-3: WebSocket endpoint (`starlette_cms/api/collab.py`)
- `WS /api/documents/{id}/collab`
- Auth: accepts either session cookie OR `?api_key=` query param (for CLI/agent tools)
- Connection lifecycle:
  1. Load `draft_body` + `draft_version` from DB (or compute from steps)
  2. Send `{ "type": "init", "doc": <draft_body>, "version": <int> }`
  3. Register connection in `CollabManager`
  4. Loop: receive messages
     - `{ "type": "steps", "steps": [...], "clientID": str, "version": int }` →
       call `authority.apply_steps(...)` →
       if accepted: broadcast `{ "type": "steps", "steps": [...], "clientIDs": [str], "version": int }` to all other connections
       if rejected: send `{ "type": "reject", "version": int }`
     - `{ "type": "ping" }` → send `{ "type": "pong" }` (keep-alive)
  5. On disconnect: remove from `CollabManager`
- Rate limiting: max 100 step messages per second per connection (drop + warn if exceeded)

#### 2-4: Wire into CMS app
- Add WebSocket route to `_build_app()` in `app.py`
- `collab_manager` instance lives on the `CMS` object (created at init time)

#### 2-5: History API
- `GET /api/documents/{id}/history`
  - Returns list of `{ version, client_id, created_at, step_count }` grouped by timestamp buckets
  - Query params: `limit=50`, `before=<ISO8601>`
- `GET /api/documents/{id}/history/{version}`
  - Reconstructs `draft_body` at the given version by replaying steps 0..version
  - Returns `{ version, body, reconstructed_at }`

#### 2-6: Tests
- `test_collab.py`:
  - Single client: connect, receive init, send steps, receive confirmation, draft_body updated in DB
  - Two clients: client A sends steps, client B receives broadcast
  - Version conflict: client sends steps with wrong version, receives reject
  - Client reconnect: receives current state
  - History reconstruction
  - Rate limit enforcement

---

## Phase 3A — embed.js Bundle Split
**Package:** `starlette-editor`  
**Complexity:** Medium  
**Depends on:** Phase 1A + 1B (knows what APIs exist)  
**Blocks:** Phase 3B, Phase 3C, Phase 4

### Goal
Split the existing monolithic editor.js into two build targets. The existing admin SPA stays
as `editor.js`. A new lightweight `embed.js` is the live-editing entry point.

### Tasks

#### 3A-1: New build targets in `esbuild.config.mjs`
- Keep existing `editor.js` output — no changes to admin SPA
- Add second entrypoint: `editor_src/embed/index.js` → `starlette_editor/static/embed.js`
- Target: `embed.js` ≤ 200KB minified (ProseMirror collab + toolbar + side panel only)
- Shared code: `api.js`, `prosemirror/mount.js`, `components/meta-panel.js` used by both

#### 3A-2: Embed entry module (`editor_src/embed/index.js`)
- Immediately invoked on load — no global namespace pollution
- Exports nothing to `window` — communicates by DOM manipulation only
- Boot sequence:
  1. Check `document.currentScript.src` to derive `cmsBase` (the origin of the embed script
     is the CMS server — no config needed)
  2. `fetch("{cmsBase}/api/auth/me")` — if `{ authenticated: false }`, stop, do nothing
  3. Find all `[data-cms-id]` elements on the page
  4. Instantiate `EditToolbar` and `ChangesetPanel`

#### 3A-3: `EditToolbar` component (`editor_src/embed/toolbar.js`)
- Floating button, bottom-right corner, `position: fixed`
- Attached to the first `[data-cms-id]` element in the viewport (or nearest scroll)
- States:
  - `viewing` — "✏️ Edit draft" button
  - `editing` — "💾 Saving..." / "✓ Saved" indicator + "Discard draft" + "Publish" + "Add to changeset"
  - `publishing` — spinner
  - `published` — "✓ Published — rebuilding site"
- CSRF token: reads from `cms_session` cookie (or a meta tag injected by the CMS shell page)

#### 3A-4: `SidePanel` component (`editor_src/embed/side-panel.js`)
- Slides in from the right when edit mode activates
- Renders structured fields (title, slug, cover_image, tags, etc.) from `/api/schema/{block_type}`
- `title` — inline `<input>` with debounced PATCH
- `slug` — displayed as read-only with a warning ("changing slug breaks URLs")
- `cover_image` — thumbnail + "Change" button → opens Mediakit picker if `data-cms-media-base` set
- `tags` — chip list with add/remove
- `published_on` — date picker
- All changes fire PATCH to `/api/documents/{id}` → write to `draft_body`

#### 3A-5: Edit mode activation (`editor_src/embed/edit-mode.js`)
- `activateEditMode(element)` — called when user clicks "Edit draft"
  1. `GET /api/documents/{id}?draft=true` — fetch draft body
  2. Replace static content in `[data-cms-field="body"]` with rendered draft HTML
  3. Call `mountProseMirror(element, { documentId, field, cmsBase, wsUrl })` from `prosemirror/mount.js`
  4. Open `SidePanel` for the document
  5. Update toolbar state to `editing`
- `deactivateEditMode(element)` — discard local ProseMirror state, restore static content
- Visual affordances:
  - Editable rich text region: 2px dashed blue outline
  - Editable inline fields: subtle highlight on hover
  - Non-editable regions: no change

#### 3A-6: Python route — serve embed.js
- Add `Route("/embed.js", endpoint=serve_embed_js)` to `starlette_editor/routes.py`
- Serves `static/embed.js` with `Content-Type: application/javascript`
- Adds `Cache-Control: public, max-age=3600` (1hr cache — ok for a JS asset)
- No auth required (the script itself is public; it checks auth at runtime)

#### 3A-7: Tests
- `test_embed_route.py`:
  - `GET /embed.js` returns 200 with JS content type
  - Embed.js builds without error (`npm run build` completes)
  - Embed.js bundle size ≤ 200KB

---

## Phase 3B — Collab Client in embed.js
**Package:** `starlette-editor`  
**Complexity:** High  
**Depends on:** Phase 2 + Phase 3A  

### Goal
`embed.js` connects ProseMirror to the WS authority. Real-time collaborative editing works.
Two browser tabs editing the same document see each other's changes immediately.

### Tasks

#### 3B-1: Collab module (`editor_src/embed/collab.js`)
- `createCollabPlugin(documentId, cmsBase, initialVersion)` — returns a ProseMirror plugin
  using `prosemirror-collab`
- Opens `wss://{cmsBase}/api/documents/{id}/collab` (upgrade from https → wss)
- On connect: receives `{ type: "init", doc, version }` — sets initial PM state
- On local edit: `sendableSteps(state)` → if non-null → send to WS
- On WS message `{ type: "steps", steps, clientIDs, version }`:
  - Apply steps that didn't originate from this client
  - Update local version
  - Re-check for sendable local steps
- On WS `{ type: "reject", version }`: rebase pending steps against new version
- Reconnect with exponential backoff on disconnect (1s, 2s, 4s, max 30s)
- Collaboration cursor: `prosemirror-view` `decorations` to show remote cursors
  (coloured caret + name label per connected `clientID`)

#### 3B-2: Mount collab-aware ProseMirror (`editor_src/prosemirror/mount.js` update)
- Extend `mountProseMirror(element, config)` to accept `{ wsUrl, initialVersion }` config
- If `wsUrl` provided: add collab plugin + cursor decorations to the plugin array
- If not provided: standard non-collab mount (admin SPA path unchanged)

#### 3B-3: Session auth in WS connection
- WS connection URL: `wss://{cmsBase}/api/documents/{id}/collab`
- Browser automatically includes cookies on WS handshake to same origin — session cookie sent
- No explicit auth header needed (cookies are sent automatically)
- Fallback: `?api_key=` query param for CLI usage (not needed for browser embed)

#### 3B-4: Tests
- `test_collab_client.js` (Vitest):
  - Collab plugin sends steps on local edit
  - Collab plugin applies received steps to local state
  - Reject message triggers rebase
  - Reconnect logic
- Python integration test with two httpx WebSocket clients simulating two editors:
  - Client A sends steps → Client B receives broadcast → both at same version

---

## Phase 3C — Changeset UI in embed.js
**Package:** `starlette-editor`  
**Complexity:** Medium  
**Depends on:** Phase 1C + Phase 3A  

### Goal
The floating toolbar shows all documents with pending changes across the site. User can
bundle them into a changeset and publish atomically.

### Tasks

#### 3C-1: `ChangesetPanel` component (`editor_src/embed/changeset-panel.js`)
- On activation, `GET /api/changesets?status=open` — fetch all open changesets
- Also `GET /api/documents?has_draft=true` — find all docs with unpublished drafts
- Shows:
  - "Unpublished changes" section: list of docs with drafts (by type + title)
  - "Open changesets" section: named changesets with their documents
- Actions per dirty document: "Add to existing changeset" (dropdown) or "Create new changeset"
- Actions per changeset: "Publish all" / "Schedule" / "Rename" / "Delete"
- "Publish all" → `POST /api/changesets/{id}/publish` → success toast, toolbar resets

#### 3C-2: Toolbar integration
- "Add to changeset" button in toolbar: opens `ChangesetPanel` with current document pre-selected
- Dirty indicator: badge on toolbar button showing count of docs with unpublished drafts
  (polls `GET /api/documents?has_draft=true` every 30s while edit mode active)

#### 3C-3: Schedule UI
- "Schedule publish" → date/time picker popover
- `POST /api/changesets/{id}/schedule { publish_at: ISO8601 }` → changeset status → "scheduled"
- Scheduled changesets show countdown in panel

#### 3C-4: Tests
- `test_changeset_panel.js` (Vitest): panel renders dirty docs and open changesets
- Python: `POST /api/changesets/{id}/publish` via test changeset → both docs published

---

## Phase 4 — Astro Frontend Wiring
**Package:** `joellithgow` (separate repo)  
**Complexity:** Low-medium  
**Depends on:** Phase 3A + 1B + 1C  

### Goal
The Astro site loads `embed.js`, marks editable regions with data attributes, and the full
live editing experience works end-to-end on the real site.

### Tasks

#### 4-1: Env var config
- Add `PUBLIC_CMS_BASE` to `.env.local` (local dev) and Netlify env vars (production)
- Value: `https://cms.joellithgow.com` (or the EC2 nginx subdomain)
- Add `PUBLIC_MEDIA_BASE` similarly (already needed for mediakit)

#### 4-2: Base layout — embed script
- `src/layouts/BaseLayout.astro`:
  ```astro
  {import.meta.env.PUBLIC_CMS_BASE && (
    <script
      src={`${import.meta.env.PUBLIC_CMS_BASE}/editor/embed.js`}
      defer
    />
  )}
  ```
- The `defer` attribute means zero impact on page performance for unauthenticated visitors —
  the script loads but immediately exits after the `auth/me` check returns false

#### 4-3: Page components — data attributes
- `src/pages/blog/[slug].astro`:
  ```astro
  <article
    data-cms-id={post.id}
    data-cms-type="blog_post"
    data-cms-base={import.meta.env.PUBLIC_CMS_BASE}
    data-cms-media-base={import.meta.env.PUBLIC_MEDIA_BASE}
  >
    <h1 data-cms-field="title">{post.title}</h1>
    <div data-cms-field="body" set:html={renderedBody} />
  </article>
  ```
- `src/layouts/BaseLayout.astro` (footer singleton):
  ```astro
  <footer
    data-cms-id={siteSettings.id}
    data-cms-type="site_settings"
    data-cms-singleton="true"
    data-cms-base={import.meta.env.PUBLIC_CMS_BASE}
  >
    <p data-cms-field="about_me">{siteSettings.about_me}</p>
  </footer>
  ```
- `src/pages/projects/[slug].astro` — same pattern for Project block type

#### 4-4: Login flow
- `src/pages/cms-login.astro` — simple redirect page:
  ```astro
  ---
  // Redirects to the CMS auth login endpoint
  return Astro.redirect(`${import.meta.env.PUBLIC_CMS_BASE}/api/auth/login?next=/`);
  ---
  ```
- Accessible at `joellithgow.com/cms-login` — Joel bookmarks this

#### 4-5: ProseMirror JSON → HTML rendering in Astro
- When Astro fetches `GET /api/documents?type=blog_post&published=true`, the `body.body` field
  is ProseMirror JSON
- Need a renderer: `src/lib/renderProseMirror.ts` using `prosemirror-model` + custom node views
- Or use `@tiptap/html` which reads ProseMirror JSON → HTML (lighter option)
- This task is about picking and wiring the renderer, not implementing PM from scratch

#### 4-6: End-to-end smoke test
- Checklist (manual, not automated):
  - [ ] Visit `joellithgow.com/cms-login` → redirect to CMS login → login → redirect back
  - [ ] Visit a blog post → floating toolbar appears
  - [ ] Click "Edit draft" → ProseMirror mounts on body, side panel slides in
  - [ ] Type in body → see "Saving..." indicator → "✓ Saved"
  - [ ] Open same URL in another tab → both tabs show same draft content
  - [ ] Edit in tab 1 → appears in tab 2 (collab)
  - [ ] "Add to changeset" → create new changeset, add footer singleton
  - [ ] "Publish all" → both docs published → one Netlify rebuild → both changes live

---

## Cross-cutting concerns

### Security checklist (applies across all phases)
- [ ] `cms_session` cookie: `httponly=True, secure=True, samesite="lax"`
- [ ] `CMS_SESSION_SECRET` env var — never hardcoded, generated with `openssl rand -hex 32`
- [ ] CSRF: all mutating endpoints with session auth check `Origin` header matches CMS host
- [ ] WS endpoint: validates session cookie on handshake — unauthenticated WS connections rejected
- [ ] `GET /api/auth/me`: `Cache-Control: no-store` — must not be CDN-cached
- [ ] `embed.js` served with `Cache-Control: public, max-age=3600` — acceptable for JS asset
- [ ] `bcrypt` used for password hashing (not SHA-256 directly)
- [ ] Rate limiting on `/api/auth/login` — max 10 attempts per IP per minute

### nginx config (EC2)
The WS authority requires nginx to proxy WebSocket connections:
```nginx
location /api/documents/collab {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400;  # keep WS alive for up to 24h
}
```

### Worker process constraint
ProseMirror collab requires that all WebSocket connections to the same document share the
same `CollabManager` instance. This means:
- **Single Uvicorn worker** (or sticky session load balancing for multi-worker)
- The `CollabManager` is an in-process singleton — it cannot be shared across workers via Redis etc. (deferred to post-v1)
- Document this constraint clearly in the CMS README

---

## ADR cross-references

| Decision | ADR |
|---|---|
| Draft/published dual state | ADR 018 |
| WS step authority | ADR 018 |
| Session auth | ADR 018 |
| Changesets | ADR 018 |
| ProseMirrorBridge in starlette-cms | ADR 004 |
| No built-in admin UI in starlette-cms | ADR 002 |
| Extension route mechanism | ADR 003 |

---

## Open questions (for future ADRs, not blockers)

1. **Multi-worker collab**: When/if the site needs >1 Uvicorn worker, the `CollabManager` must
   move to Redis pub/sub. Deferred — document the single-worker constraint now.
2. **Offline editing**: Should unsaved steps survive a page refresh? Would require IndexedDB
   buffering on the client. Not in scope for this implementation.
3. **Cursor names**: The `clientID` sent in collab steps is currently an anonymous UUID. A
   future enhancement shows the editor's display name (from session `sub`). Deferred.
4. **Block-level inline editing**: Complex nested blocks (e.g. `ListField` with sub-blocks) are
   rendered as ProseMirror nodes. Full inline editing of these requires ProseMirror node views —
   the existing admin SPA block canvas is the fallback for these until node views are implemented.
