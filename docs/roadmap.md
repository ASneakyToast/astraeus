# Astraeus — Implementation Roadmap

Phases are ordered by dependency. A future agent should always start at the earliest incomplete phase.

**Current status:** Phases 0–4 complete (including EPIC-001 VPP MVP primitives).

**Use cases:** See `docs/use-cases/` for worked examples of Astraeus applied to real projects. These inform roadmap priorities and surface new primitives.

**Primary (original design driver):**
- [`personal-site-joellithgow.md`](use-cases/personal-site-joellithgow.md) — agent-driven publishing for joellithgow.com; drives MCP server (Phase 5), editor auto-generation (Phase 10), and the webhook→build trigger architecture

**Extended (discovered through real-world application):**
- [`vpp-underwriting-intake.md`](use-cases/vpp-underwriting-intake.md) — structured intake forms as governed documents; drives `NumberField`, `SelectField`, `BoolField`, `URLField` and validates schema API for external consumers
- [`vpp-rule-governance.md`](use-cases/vpp-rule-governance.md) — actuarial rule parameters as singleton governed config; drives singleton pattern (ADR 009) and compliance/audit narrative
- [`vpp-eval-dataset.md`](use-cases/vpp-eval-dataset.md) — human-scored AI runs as documents; introduces `DocumentRef` (ADR 010) and closes the governed feedback loop
- [`vpp-test-case-library.md`](use-cases/vpp-test-case-library.md) — curated test scenarios as authored fixtures; drives `JSONField` and webhook-triggered CI pattern
- [`vpp-prompt-versioning.md`](use-cases/vpp-prompt-versioning.md) — AI pipeline prompts as singleton governed config; extends ADR 009 and positions Astraeus for production AI use cases

Together these establish Astraeus as a **governed data platform** — not just a headless CMS. The personal site is the original use case and remains the primary one; the VPP use cases extend the same primitives into AI system governance territory.

---

## Phase 0 — Scaffold ✅

- [x] UV workspace monorepo
- [x] All three package `pyproject.toml` files
- [x] Package skeleton (`__init__.py`, field types, registry, app stub, exceptions)
- [x] `CLAUDE.md`, `docs/architecture.md`, `docs/roadmap.md`, ADRs
- [x] `examples/demo/app.py`
- [x] Initial GitHub push

---

## Phase 1 — starlette-cms core ✅

**Goal:** A running CMS server that can create, read, update, delete, and publish documents via HTTP. No migrations, no webhooks yet — just the core data layer and API.

**Done when:** `examples/demo/app.py` starts without errors, and all endpoint tests pass.

### 1a — Pydantic model generation from block definitions ✅
- [x] `@block` / `@cms.block` decorator injects `block_type: Literal[name]` field
- [x] Field types (`TextField`, `RichTextField`, `ImageField`, `ListField`, `BlockField`) generate correct Pydantic `FieldInfo`
- [x] `ListField(blocks=[...])` generates discriminated union via `Union[...] + Field(discriminator="block_type")`
- [x] Self-referential blocks via string forward refs + `model_rebuild()`
- [x] `@cms.document()` decorator builds the document Pydantic model

### 1b — Piccolo ORM + SQLite ✅
- [x] `cms_documents` table (id, type, slug, body JSON, meta JSON, created_at, updated_at, published, published_at)
- [x] `cms_meta` table (key, value) — stores `schema_version`
- [x] WAL mode enabled on SQLite init
- [x] Lifespan context opens and closes the DB connection

### 1c — Document CRUD API ✅
- [x] `GET /api/documents` — list with `type`, `slug`, `published`, `limit`, `offset` query params
- [x] `POST /api/documents` — create, validates body against registered block schemas
- [x] `GET /api/documents/{id}` — get by nanoid
- [x] `PATCH /api/documents/{id}` — partial update
- [x] `DELETE /api/documents/{id}` — hard delete
- [x] `POST /api/documents/{id}/publish` — set published=true, published_at=now
- [x] `POST /api/documents/{id}/unpublish` — set published=false

### 1d — Auth middleware ✅
- [x] Mode: `"none"` — all routes open
- [x] Mode: `"apikey"` — mutating endpoints require `Authorization: Bearer {key}`
- [x] Mode: callable — `async (request) -> bool`, applied to mutating endpoints
- [x] `read_auth=True` flag extends auth to GET endpoints

### 1e — Schema introspection ✅
- [x] `GET /api/schema` — JSON Schema for all registered block types
- [x] `GET /api/schema/{block_type}` — JSON Schema for one block type, including `cms:field_meta`
- [x] `GET /api/schema/version` — current schema version string

### 1f — Nanoid document IDs ✅
- [x] `nanoid` generates document IDs at create time
- [x] IDs are opaque strings, not sequential integers

### 1g — Extension route mechanism ✅
- [x] `cms.register_extension_route()` stores routes in a list
- [x] `cms.app` (lazy property) builds the Starlette app, including extension routes, on first access
- [x] Calling `register_extension_route()` after `cms.app` is accessed raises `RuntimeError`

### 1h — Tests ✅
- [x] Unit tests for block decorator + Pydantic model generation
- [x] Unit tests for registry (register, collision, override, discover)
- [x] Integration tests for all document CRUD endpoints (httpx + ASGITransport)
- [x] Integration tests for auth modes
- [x] Integration tests for schema introspection

---

## Phase 2 — starlette-cms schema versioning ✅

**Goal:** The CMS detects version mismatches on startup and refuses to run until migrations are applied.

**Done when:** `cms migrate` CLI works end-to-end and the startup check correctly blocks on mismatch.

- [x] `cms_meta` stores `schema_version = "{package_version}"`
- [x] On startup: read `schema_version`, compare to package version, raise `CMSSchemaMismatch` on mismatch
- [x] `@cms.migration(from_version, to_version)` decorator registers migration functions
- [x] Migration chain runner — executes functions in order, updates `schema_version` after each
- [x] `cms migrate status` — shows pending migrations
- [x] `cms migrate --dry-run` — shows what would run
- [x] `cms migrate` — applies pending migrations
- [x] `cms validate` — checks all stored documents validate against current block schemas

---

## Phase 3 — starlette-cms webhooks + polish ✅

**Goal:** Publish events trigger registered webhook URLs. The core CMS is production-ready.

**Done when:** Publishing a document fires registered webhooks, and `examples/demo` works end-to-end including Netlify rebuild trigger.

- [x] `GET /api/webhooks` — list registered webhooks
- [x] `POST /api/webhooks` — register a URL + event list
- [x] `DELETE /api/webhooks/{id}` — remove a webhook
- [x] Webhook delivery on: `document.created`, `document.updated`, `document.deleted`, `document.published`, `document.unpublished`
- [x] Webhook payload: `{ event, document_id, document_type, slug, timestamp }`
- [x] Fire-and-forget delivery (v1 — no retry queue)
- [x] `ImageField` + `MediaBackend` protocol — if configured, validate image keys on save

---

## Phase 4 — starlette-cms testing utilities + VPP MVP primitives (EPIC-001) ✅

**Goal:** Testing utilities for block authors, plus all primitives needed for the VPP underwriting MVP.

**Done when:** All six EPIC-001 stories pass, acceptance smoke test green (241 tests).

### 4a — Testing utilities (STORY-006) ✅
- [x] `validate_block(block_cls, data)` — validates dict against block, returns model or raises `ValidationError`
- [x] `BlockTestCase.assert_valid/invalid/fields/field_label/field_required/field_optional/roundtrip`
- [x] `RegistryTestCase` — fresh CMS per test, `assert_registered`, `assert_no_collision`
- [x] `contrib/blocks/basic.py` blocks are tested using `BlockTestCase`

### 4b — New field types (STORY-001) ✅
- [x] `NumberField` — float with optional `min_value`, `max_value`, `precision`
- [x] `SelectField` — string constrained to a `choices` list (Pydantic `Literal` enum)
- [x] `BoolField` — boolean with configurable default
- [x] `URLField` — string with `format: url` in `cms:field_meta`
- [x] `JSONField` — arbitrary dict/list, maps to `Any` in Pydantic

### 4c — Singleton documents (STORY-002) ✅
- [x] `@cms.block("name", singleton=True)` marks a block as singleton
- [x] `singleton_status` column (`active` / `archived`) on `cms_documents`
- [x] Archive-then-activate publish semantics (only one active at a time)
- [x] `GET /api/singletons/{block_type}` — fetch active singleton
- [x] `POST /api/singletons/{block_type}/publish` — publish new version
- [x] `GET /api/singletons/{block_type}/history` — version history
- [x] `cms.documents.get_singleton(block_type)` Python accessor

### 4d — Immutable fields (STORY-003) ✅
- [x] `immutable=True` flag on any `_BaseField` subclass
- [x] `__immutable_fields__` set on generated Pydantic models
- [x] PATCH endpoint strips immutable fields from update payload
- [x] `immutable: true` in `cms:field_meta` schema output

### 4e — DocumentRef (STORY-004) ✅
- [x] `DocumentRef(block_type=..., on_delete="block"|"nullify"|"cascade")` field type
- [x] `__ref_fields__` mapping on generated models
- [x] `_validate_refs()` — checks referenced doc exists and has correct block_type on create/patch
- [x] `_check_ref_integrity()` — enforces `on_delete` semantics on delete
- [x] `_bulk_resolve_refs()` — O(1)-per-field inline resolution in list responses
- [x] `resolve_refs` query param on `GET /api/documents`

### 4f — List filters (STORY-005) ✅
- [x] `filters=` JSON query param for body-field filtering
- [x] `filter[key]=value` bracket syntax alternative
- [x] `order_by` and `order` (asc/desc) query params
- [x] `_coerce_filter_value()` — URL string to bool/int/float/str
- [x] `_matches_filters()` — Python-level body field matching (v1)
- [x] `cms.documents.list(block_type, filters=...)` Python accessor
- [x] `filters_applied` in list response metadata

---

## Phase 5 — starlette-cms MCP server ✅

**Goal:** An agent (Claude Code, Claude Desktop) can create, edit, and publish documents using tools.

**Done when:** Running `starlette-cms mcp serve --url ... --api-key ...` registers tools that a connected agent can call successfully against a live CMS.

- [x] `pip install starlette-cms[mcp]` installs `mcp` dependency
- [x] `starlette-cms mcp serve --url {base_url} --api-key {key}` starts MCP server
- [x] Tools: `list_documents`, `get_document`, `create_document`, `update_document`, `delete_document`, `publish_document`, `unpublish_document`, `list_block_types`, `get_block_schema`
- [x] Tool descriptions are agent-legible (explain what each arg does, what gets returned)
- [x] Auth passed as `Authorization: Bearer {key}` header on every request

---

## ADR 014 — append_only=True documents ✅

**Goal:** Machine-written audit records with structural immutability — auto-published on creation, frozen body, cannot be deleted.

**Done when:** POST creates and publishes in one call; PATCH and DELETE return 405; read endpoints unaffected.

- [x] `append_only: bool` on `BlockRegistration`, `@block()`, and `@cms.block()`
- [x] `BlockRegistry.is_append_only()` introspection method
- [x] `POST /api/documents` with append_only block type → auto-publishes atomically
- [x] `PATCH /api/documents/{id}` on append_only document → 405 Method Not Allowed
- [x] `DELETE /api/documents/{id}` on append_only document → 405 Method Not Allowed
- [x] `ImmutableDocumentError` exception exported from `starlette_cms`
- [x] Webhook for append_only creation carries `append_only: true` in extra payload
- [x] `POST /api/documents` falls back to block registry for append_only / singleton types

---

## Phase 6 — mediakit core ✅

**Goal:** A running Mediakit server that can accept uploads, serve IIIF derivatives, and maintain the catalog.

**Can develop in parallel with starlette-cms Phases 2–4.**

**Done when:** The upload flow works end-to-end against a real S3-compatible bucket, IIIF derivatives are generated and cached, and the catalog accurately reflects the bucket state.

### 6a — Storage backend ✅
- [x] `S3CompatibleBackend`: `prepare_upload`, `confirm_exists`, `get_url`, `delete`, `list_objects`
- [x] Presigned PUT URL generation (obstore)
- [x] Presigned GET URL generation
- [x] Public URL mode (`public_read=True`)
- [x] Works against GCS, Cloudflare R2, AWS S3 (endpoint_url configuration)

### 6b — Upload flow ✅
- [x] `POST /upload/prepare` — validates request, generates presigned PUT URL, returns `{ upload_url, key, expires_at }`
- [x] `POST /upload/confirm` — verifies object exists, runs processing pipeline, inserts into catalog
- [x] Processing pipeline: EXIF strip, WebP conversion, max dimension cap (Pillow) — `mediakit/processing/pipeline.py`
- [x] Content-addressed key generation: `originals/{sha256_prefix}/{filename}`

### 6c — Catalog ✅
- [x] `Catalog.insert_asset`, `get_asset`, `list_assets`, `update_asset`, `delete_asset`
- [x] `get_or_create_derivative`, `insert_derivative`
- [x] `set_references` (upsert-and-replace), `remove_references`
- [x] `find_orphans`, `export_csv`

### 6d — IIIF Image API ✅
- [x] IIIF URL parsing and parameter validation — `mediakit/routes/iiif.py`
- [x] Level 1 compliance: `full/square/x,y,w,h` region; `full/max/w,/,h/w,h/!w,h` size; `0/90/180/270` rotation; `default/color/gray` quality; `jpg/webp/png` format
- [x] `GET /iiif/{key}/info.json`
- [x] `GET /iiif/{key}/{region}/{size}/{rotation}/{quality}.{format}` — 302 redirect to cached derivative (or generate + cache)

### 6e — Asset routes ✅
- [x] `GET /assets` — paginated, filterable
- [x] `GET /assets/{key}` — metadata + URL
- [x] `PATCH /assets/{key}` — update alt_text, tags
- [x] `DELETE /assets/{key}` — removes from bucket, catalog, and all references

### 6f — References route ✅
- [x] `POST /references` — upsert-and-replace for a content record
- [x] `DELETE /references` — remove all references for a content record

### 6g — Auth ✅
- [x] Same three modes as starlette-cms: none, apikey, callable

---

## Phase 7 — mediakit admin UI

**Goal:** A usable browser interface for uploading and browsing assets, including picker mode.

- [ ] `GET /admin` — asset browser grid (IIIF square/256, thumbnails)
- [ ] Normal mode: click → detail view with metadata editor
- [ ] Picker mode (`?picker=1`): click → `postMessage("mediakit:asset-selected", ...)` + close
- [ ] Cancel button → `postMessage("mediakit:picker-cancelled", ...)`
- [ ] `GET /admin/upload` — drag-and-drop uploader (vanilla JS, no framework)
- [ ] Filtering by type and tag

---

## Phase 8 — mediakit MCP server

**Goal:** An agent can list, search, and manage media assets using tools.

- [ ] `pip install mediakit[mcp]`
- [ ] `mediakit mcp serve --url {base_url} --api-key {key}`
- [ ] Tools: `list_assets`, `get_asset`, `search_assets`, `update_asset`, `delete_asset`, `get_iiif_url`

---

## Phase 9 — mediakit CLI

- [ ] `mediakit sync` — walk bucket, reconcile against catalog, insert missing records
- [ ] `mediakit gc` — remove orphaned derivatives and unconfirmed upload temporaries
- [ ] `mediakit export` — export catalog as CSV

---

## Phase 10 — starlette-editor Phase 1 (foundation) ✅

**Prerequisite:** starlette-cms Phase 1 complete.

**Goal:** The ProseMirror bridge works and `<se-block-editor>` renders a live editor for a `RichTextField`.

- [x] `ProseMirrorBridge.generate_schema()` — derives ProseMirror schema + `blockTypes` metadata from BlockRegistry
- [x] `/api/editor-schema` endpoint (registered on CMS via extension route)
- [x] `RichTextField.field_meta()` emits `"field_type": "rich_text"`; `ImageField` emits `"field_type": "image"`
- [x] `fieldWidget()` in `editor.js` driven by `field_type` from `cms:field_meta` (heuristics kept as fallback)
- [x] PM doc init/save: `RichTextField` round-trips as ProseMirror JSON (not markdown)
- [x] Editor SPA (`editor.js`) already ships as working vanilla JS; no esbuild/TypeScript pipeline needed at this phase
- [x] Tests: `test_prosemirror_bridge.py` (13), `test_rich_text_field_meta.py` (3), `test_editor_schema_integration.py` (4)

---

## Phase 11 — starlette-editor Phase 2 (StandardEditor)

- [ ] Full StandardEditor SPA (document list + block canvas)
- [ ] Block picker dropdown, block card, drag-and-drop reordering
- [ ] Publish/unpublish flow, meta panel
- [ ] Auth shell protection + API key injection via `window.__EDITOR_CONFIG__`

---

## Phase 12 — starlette-editor Phase 3 (media + custom editors)

- [ ] `<se-image-picker>` with Mediakit picker protocol
- [ ] `<se-block-picker>`
- [ ] `core.js` bundle (EditorContext for custom editors)
- [ ] Node views for nested block types
- [ ] Richtext toolbar

---

## Personal site integration (ongoing)

**Not a numbered phase — runs in parallel once Phase 1 is stable.**

- [ ] Deploy starlette-cms + mediakit backend (Fly.io or Railway)
- [ ] Add `[tool.uv.sources]` to joellithgow pointing at local packages during dev
- [ ] Migrate Astro content from MDX files to CMS API fetches
- [ ] Register Netlify build hook as a webhook
- [ ] Configure Claude Code MCP servers (starlette-cms + mediakit)
- [ ] Blog post: "Building Astraeus and using it on my own site"

---

## North Star (post-v1, don't implement yet)

- Collaborative editing via `cms_steps` table + WebSocket authority endpoint + `prosemirror-collab`
- SQLite FTS5 or Postgres `tsvector` full-text search
- Draft/revision history
- Block package marketplace / curated index
- `starlette-suite` meta-package convenience install
