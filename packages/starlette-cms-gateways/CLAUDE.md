# starlette-cms-gateways — Agent Instructions

Read `../../CLAUDE.md` (the root Astraeus instructions) before working in this package.
Then read `../../docs/decisions/015-starlette-cms-gateways.md` — it defines this package's scope and constraints —
and `../../docs/decisions/023-gateway-state-and-publishing.md`, which supersedes ADR 015's cursor, state and
incremental-sync sections (so where they disagree, ADR 023 wins).

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
├── base.py          # BaseGateway ABC + sync loop, SyncRange/SyncWindow, field ownership, refetch hook
├── client.py        # CMSClient — upsert (create/update/skip/defer), find_by_import_ref, gateway API calls
├── drafts.py        # draft_verdict — is a pending draft the gateway's own or a person's?
├── state.py         # SyncState protocol, RetryEntry, RemoteSyncState (state over the CMS gateway API)
├── jobstore.py      # JobStore — cursor, retry list and job history in the CMS's SQLite file
├── runner.py        # run_recorded — run a gateway and keep job history true, from any entry point
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

**Sync state lives in the CMS, and workers reach it through the CMS.** The cursor, the retry list and the job
history are tables in the CMS's own database (`GatewayAdmin` defaults to that file). Only the CMS process opens
it; the CLI and MCP sidecars use `RemoteSyncState` over `/api/gateways/{name}/cursor|retry|runs`. Never give a
worker its own state file: that is two cursors, lost on restart. Run every sync through `run_recorded` so job
history covers all entry points.

**The cursor is opt-in per gateway, and it never freezes.** The framework does not inject a `since` into
`fetch()` (ADR 015). It passes the *request* as `self.range`; a gateway that wants a datetime cursor calls
`await self.resolve_window()`. After any run that did not raise the cursor becomes the run's *start* time (never
after `custom`). Items a run deferred or failed on go on the retry list, not into the cursor; a gateway can
implement `refetch(import_refs)` to rebuild them next run. Never use `get_last_synced()` as a cursor: it is when a
run *finished*.

**Declare `owned_fields`.** Only owned (machine-sourced) fields are hashed and written on update; everything
else is written once at creation and left to whoever edits it. Never write a field a person might edit in the
editor into an update. A re-sync that finds nothing new must make zero writes. A gateway with no `owned_fields`
cannot tell its own pending draft from a person's, so it defers on any draft.

**Each document is published as soon as it is written** (`auto_publish`), one at a time: no end-of-run changeset
publish. The PATCH sends `X-Skip-Changeset` so the CMS does not open a date-titled changeset per document. A
person's draft (or a document a person unpublished) is deferred, never patched or published over; the gateway's
*own* leftover draft is finished.

**Gateway implementations go in consumer repos, not here.** If you are adding a new gateway for a
specific service, it belongs in the consuming application's codebase and entry points, not in this package.
The `examples/` directory is documentation only.

---

## Key ADRs and decisions

- **ADR 015** (`docs/decisions/015-starlette-cms-gateways.md`) — this package's architecture, including EPIC-002 amendments. Its cursor / incremental-sync sections are superseded by ADR 023
- **ADR 023** (`docs/decisions/023-gateway-state-and-publishing.md`) — sync state in the CMS, the never-freezing cursor and retry list, draft ownership, per-document publishing
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

**Testing.** The root rule wins: anything that touches draft, publish, changeset or sync-state behaviour runs
against a real CMS in-process (`ASGITransport`, a temp SQLite file; never a separate process), because a mock
can only repeat what you told it the CMS does. That is `test_sync_state.py`, `test_sync_ownership.py`,
`test_sync_e2e.py` and `test_gateway_admin.py`. `respx` is for the request shape of `CMSClient` alone
(`test_cms_client.py`) and for faking the *external* service a gateway pulls from. Include a restart case when you
touch state: build a second CMS on the same file. Integration tests (if any) live in `tests/integration/` and
require `CMS_URL` and `CMS_API_KEY` env vars.
