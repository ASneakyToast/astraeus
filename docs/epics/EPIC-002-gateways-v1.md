# EPIC-002 — Gateways v1: Framework Completion + First Real Consumers

**Status:** Ready for implementation
**Date:** 2026-06-28
**Source:** [Product interview notes](../decisions/gateways-interview-2026-06.md)
**Packages:** `starlette-cms-gateways`, `astraeus-otel` (new), `starlette-cms` (minor)

---

## Overview

The `starlette-cms-gateways` framework skeleton is complete (BaseGateway, CMSClient,
GatewaySyncState, CLI, MCP server — 44 tests passing). This epic makes it production-ready and
validates it against three real consumer use cases:

1. **Spotify** — joellithgow.com (liked songs / listening activity)
2. **iNaturalist** — joellithgow.com (nature observations)
3. **GitHub** — lzr-skills app (releases/activity; first webhook-triggered gateway)

The primary design constraint from the interview: **SQLite only, no queue infrastructure**.
All design decisions must hold under that constraint.

---

## Scope

### In scope

| Story | Change | Why |
|---|---|---|
| [STORY-001](#story-001) | Remove `GatewaySyncState`; drop `since` as framework primitive | Simplifies framework; OTEL is the observability layer |
| [STORY-002](#story-002) | Make gateway blocks mutable (`append_only=False` default) | Joel always annotates synced items post-creation |
| [STORY-003](#story-003) | Add `auto_publish: bool = False` to gateway class config | Some gateways auto-publish; personal site uses draft-by-default |
| [STORY-004](#story-004) | Implement three trigger types: `time-based`, `webhook`, `manual` | Supports cron, GitHub webhooks, and CLI-manual use cases |
| [STORY-005](#story-005) | Optional failure webhook on the gateway class | Log always; optionally POST to a configurable URL on sync failure |
| [STORY-006](#story-006) | Implement ADR 017 (OTel) in `starlette-cms-gateways` + new `astraeus-otel` package | All sync errors must be observable before going to production |
| [STORY-007](#story-007) | Build Spotify gateway in joellithgow repo | First real consumer; validates the full stack |
| [STORY-008](#story-008) | Build iNaturalist gateway in joellithgow repo | Second consumer; confirms pattern generalises |
| [STORY-009](#story-009) | Build GitHub gateway (lzr-skills) | First webhook-triggered gateway; onboards lzr-skills to Astraeus |

### Out of scope

- Built-in migration registration — deferred until multiple real consumers exist (file an ADR when relevant)
- Queue infrastructure of any kind (Redis, Postgres, arq, procrastinate) — SQLite constraint
- Editor UI for gateway management — CLI + logs is sufficient for now
- Retry/backoff in the framework — handled at the cron/orchestration layer or by OTel alerting

---

## Key design decisions (settled — do not relitigate)

- **`since` is not a framework primitive.** Each gateway owns its own fetch logic and cursor/state
  internally. The framework does not prescribe time-based filtering.
- **`GatewaySyncState` is dropped.** OTEL is the observability layer. Gateways manage their own
  state if they need it.
- **Draft-by-default.** All synced documents land with `published=False` unless the gateway class
  sets `auto_publish = True`.
- **Webhook trigger = fire-and-forget subprocess.** Starlette endpoint receives webhook, fires
  `gateways sync <name>` as a subprocess, returns 200 immediately. No queue.
- **`append_only` defaults to `False`.** Gateway blocks are mutable. Immutable is opt-in for
  audit-style gateways.

---

## Dependency order

```
STORY-001 (remove GatewaySyncState + since)
    │
    ├─ STORY-002 (mutable blocks)        ← touches BaseGateway
    │
    └─ STORY-003 (auto_publish config)   ← touches BaseGateway

STORY-004 (trigger types)
    │
    └─ STORY-005 (failure webhook)       ← extends trigger error handling

STORY-006 (OTel / ADR 017)             ← independent; should land before STORY-007+

STORY-007 (Spotify)    ← depends on STORY-001 through STORY-006 complete
STORY-008 (iNaturalist) ← depends on STORY-007 pattern validated
STORY-009 (GitHub)      ← depends on STORY-004 webhook trigger complete
```

---

## Stories

### STORY-001

**Remove `GatewaySyncState` and `since` as framework primitives**

- Delete `GatewaySyncState` model and all references in the framework
- Remove `since: datetime | None` parameter from `BaseGateway.fetch()` signature
- Update `CMSClient` and CLI — remove any state tracking calls
- Update all tests accordingly
- Update `docs/decisions/015-starlette-cms-gateways.md` to reflect the change

**Acceptance:** All 44 existing tests pass (adjusted). No references to `GatewaySyncState` or
`since` remain in the framework code.

---

### STORY-002

**Make gateway blocks mutable by default**

- Change `append_only` default on gateway block registration from `True` to `False`
- Add explicit opt-in: `@gateway.block(immutable=True)` for audit-style gateways
- Ensure PATCH endpoint works on gateway-synced documents
- Test: annotate a synced document post-creation; verify patch succeeds

**Acceptance:** Gateway blocks are patchable by default. `immutable=True` opt-in still enforces
append-only. Tests cover both paths.

---

### STORY-003

**Add `auto_publish` config to gateway class**

- Add `auto_publish: bool = False` class attribute to `BaseGateway`
- When `auto_publish=False` (default): synced documents created with `published=False`
- When `auto_publish=True`: synced documents created with `published=True` and `published_at` set
- Document in docstring and ADR 015

**Acceptance:** Default sync creates draft documents. `auto_publish=True` gateway publishes
immediately. Tests cover both.

---

### STORY-004

**Implement three trigger types: `time-based`, `webhook`, `manual`**

- Add `trigger: Literal["time-based", "webhook", "manual"]` class attribute to `BaseGateway`
- **`manual`** — existing CLI behaviour; formalise it
- **`time-based`** — cron-friendly; `gateways sync <name>` is the interface; no framework
  changes needed beyond documenting the pattern and ensuring the CLI exit codes are correct
  (0 = success, 1 = sync error, 2 = config error)
- **`webhook`** — new Starlette endpoint `POST /gateways/{name}/trigger` that fires
  `gateways sync <name>` as a subprocess and returns `202 Accepted` immediately. Optionally
  accepts a shared secret header for basic auth (`GATEWAY_WEBHOOK_SECRET` env var).
- Register `/gateways/` routes via `register_extension_route()` on the CMS app

**Acceptance:** Webhook endpoint fires subprocess and returns 202. CLI exit codes documented
and tested. Trigger type is inspectable on the gateway class.

---

### STORY-005

**Optional failure webhook on sync error**

- Add `failure_webhook_url: str | None = None` class attribute to `BaseGateway`
- On any unhandled sync error: if `failure_webhook_url` is set, POST a JSON payload:
  ```json
  {
    "gateway": "<name>",
    "error": "<message>",
    "traceback": "<optional>",
    "timestamp": "<iso8601>"
  }
  ```
- POST is best-effort (fire-and-forget, log if it fails, never raise)
- Configurable via env var pattern consistent with the rest of the framework

**Acceptance:** On sync failure, webhook fires if configured. Failure of the failure webhook
itself is logged but does not raise. Tests cover both configured and unconfigured cases.

---

### STORY-006

**Implement ADR 017 (OTel) in `starlette-cms-gateways` + new `astraeus-otel` package**

This is the most infrastructure-heavy story. Implement ADR 017 as written:

- Add `structlog` + `opentelemetry-api` as direct dependencies of `starlette-cms-gateways`
- Replace all `click.echo(err=True)` operational calls with `logger.warning/error` structured calls
- Replace the `"log but don't raise"` comment in `client.py` with an actual log call
- Add OTEL spans on the sync critical path (fetch, transform, write)
- Add `--verbose` / `--quiet` flags to CLI
- Create new `packages/astraeus-otel/` package per ADR 017 spec:
  - `setup_telemetry(config: TelemetryConfig | None = None)`
  - `TelemetryConfig(BaseSettings)` reading `OTEL_*` + `ASTRAEUS_*` env vars
  - Wires TracerProvider + LoggerProvider + structlog processor chain
- CLI calls `setup_telemetry()` at startup

**Acceptance:** No silent swallows remain in gateways code. Sync errors appear as structured
log lines. `astraeus-otel` package installs cleanly and `setup_telemetry()` works with no
arguments (env-var-driven).

---

### STORY-007

**Build Spotify gateway** *(in joellithgow repo)*

- Implement `SpotifyGateway(BaseGateway)` against the Spotify Web API
- Fetch: recently played tracks or saved/liked songs (TBD based on API access)
- Block schema: `track_name`, `artist`, `album`, `spotify_url`, `listened_at` (at minimum)
- `auto_publish = False` — all items land as drafts
- `trigger = "time-based"` — run via cron
- Gateway manages its own cursor/timestamp state internally (not via framework)
- OAuth token handling: stored in env vars or a secrets file; not in the CMS DB

**Acceptance:** `gateways sync spotify` creates draft documents in starlette-cms. Re-running
does not duplicate items (idempotent on `import_ref`). Joel can annotate and publish via MCP
or editor.

---

### STORY-008

**Build iNaturalist gateway** *(in joellithgow repo)*

- Implement `iNaturalistGateway(BaseGateway)` against the iNaturalist API
- Fetch: observations by Joel's user ID, filtered by date range (gateway manages internally)
- Block schema: `species_name`, `common_name`, `observed_at`, `location`, `photo_url`,
  `inaturalist_url` (at minimum)
- `auto_publish = False`
- `trigger = "time-based"`

**Acceptance:** Same idempotency and draft-creation criteria as STORY-007.

---

### STORY-009

**Build GitHub gateway** *(in lzr-skills repo)*

- Implement `GitHubGateway(BaseGateway)` against the GitHub API or webhook payload
- `trigger = "webhook"` — first webhook-triggered gateway in the ecosystem
- Fetch: releases or push events for the lzr-skills repo
- Block schema: TBD based on what lzr-skills actually needs
- This story also bootstraps lzr-skills as an Astraeus consumer — wire up starlette-cms
  as a dependency and register the gateway

**Acceptance:** GitHub webhook fires `POST /gateways/github/trigger` on the lzr-skills
Astraeus instance, which creates a draft document. Webhook secret validation passes.

---

## Testing notes

- STORY-001 through STORY-006 must all pass in the monorepo test suite before STORY-007+
- Gateway implementation stories (007–009) live in their respective app repos and are
  validated by running `gateways sync` against a local CMS instance
- Use `RegistryTestCase` for any new starlette-cms-level tests
- Use `httpx.AsyncClient` + `ASGITransport` for webhook endpoint tests
