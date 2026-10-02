# starlette-cms-gateways — Agent Instructions

Read `../../CLAUDE.md` (the root Astraeus instructions) before working in this package.
Then read `../../docs/decisions/015-starlette-cms-gateways.md` — it defines this package's scope and constraints.

---

## What this package is

`starlette-cms-gateways` is a **framework** for pulling external service data into starlette-cms as documents.
It provides:

- `BaseGateway` — abstract base class; consumer implements `fetch()`, framework handles the sync loop
- `CMSClient` — thin httpx wrapper for the starlette-cms HTTP API
- `gateways` CLI — plugin-based command that discovers gateways via entry points

**This package ships zero built-in gateway integrations.** Spotify, iNaturalist, GitHub, etc. are
consumer-level concerns. The `examples/` directory contains reference implementations for documentation
purposes only — they are not installed as part of the package.

---

## Package structure

```
src/starlette_cms_gateways/
├── __init__.py      # public API: BaseGateway, GatewayItem, SyncRange, SyncResult, SyncWindow
├── base.py          # BaseGateway ABC + sync loop, SyncRange/SyncWindow, field ownership
├── client.py        # CMSClient — upsert (create/update/skip/defer), find_by_import_ref
├── jobstore.py      # JobStore — sync job history + per-gateway sync cursor (SQLite)
├── cli.py           # gateways CLI group (sync [--range/--from/--to], list)
└── mcp/
    └── server.py    # build_gateway_mcp_server() factory [requires mcp extra]
examples/
├── spotify_liked_songs/
└── inaturalist_outings/
```

---

## Critical constraints

**`import_ref` is the dedup key.** Format: `"{service}:{subtype}:{external_id}"` — e.g.
`"spotify:liked:abc123"`. Never use the slug as a dedup key. The CMS API exposes
`GET /api/documents?import_ref=...` — use it.

**The gateway worker is always an external process.** It calls the CMS over HTTP. Do not add a background
thread or scheduler inside the CMS or this package. See ADR 005 and ADR 015.

**`auto_publish` is a class-level flag, not a runtime parameter.** Set it at the class level when defining
a `BaseGateway` subclass. Do not pass it to `sync()`.

**Cursor management is opt-in, and the gateway decides how to use it.** The framework does not inject a
`since` parameter into `fetch()` (ADR 015). It passes the *request* as `self.range` (`since_last_sync`,
`all_time` or `custom`). A gateway that wants a datetime cursor calls `await self.resolve_window()`; only then
does the framework advance the cursor, after a clean run, in `JobStore`. Gateways with another cursor shape
(a page token, an event id) ignore all of this and keep their own.

**Declare `owned_fields`.** Only owned (machine-sourced) fields are hashed and written on update; everything
else is written once at creation and left to whoever edits it. Never write a field a person might edit in the
editor into an update. A re-sync that finds nothing new must make zero writes.

**An update on an `auto_publish` gateway is published, in the run's changeset.** A document with a pending
human draft is deferred, never patched or published over.

**Gateway implementations go in consumer repos, not here.** If you are adding a new gateway for a
specific service, it belongs in the consuming application's codebase and entry points, not in this package.
The `examples/` directory is documentation only.

---

## Key ADRs and decisions

- **ADR 015** (`docs/decisions/015-starlette-cms-gateways.md`) — this package's architecture, including EPIC-002 amendments
- **ADR 005** — gateway workers are external HTTP clients of the CMS (never embedded)

---

## Development

```bash
# Install with all extras
uv sync --package starlette-cms-gateways --extra full

# Run tests
uv run pytest packages/starlette-cms-gateways/

# Type check
uv run pyright packages/starlette-cms-gateways/

# Lint
uv run ruff check packages/starlette-cms-gateways/
```

Tests use `respx` to mock the CMS HTTP API — never spin up a real CMS process in unit tests. The sync
behaviour that depends on the CMS's real draft/changeset semantics (`test_sync_ownership.py`,
`test_sync_e2e.py`) runs a CMS in-process over `ASGITransport`, not as a process.
Integration tests (if any) live in `tests/integration/` and require `CMS_URL` and `CMS_API_KEY` env vars.
