# ADR 015 — starlette-cms-gateways: external service gateway framework

**Status:** Accepted (supersedes original 2026-06-19 draft — see Design History)
**Date:** 2026-07-05

---

## Context

starlette-cms stores structured content authored by humans via the editor UI or MCP tools. A distinct class
of content is *aggregated activity* pulled from external services on a schedule: music you've been listening
to, wildlife observations logged during a walk, GitHub releases you've published, books you've finished.

Simon Willison calls these "beats" on his blog — slim timeline events that represent external activity mixed
into a content feed. The pattern is well-proven: a periodic job fetches from an external API, upserts records
into the content store using a stable external ID as a deduplication key, and the frontend queries and displays
them alongside authored content.

starlette-cms does not have a native deduplication primitive. Slugs are URL paths, not stable external IDs.
Without `import_ref`, a gateway worker has no reliable way to detect an existing record without expensive
full-body comparison. The solution is a dedicated nullable indexed column — exactly as Simon's Django blog
uses `import_ref` on its `Beat` model.

starlette-cms also has no framework for the gateway sync loop itself: fetch-from-external, upsert-with-dedup,
expose via CLI. This repeating pattern belongs in a reusable package rather than copy-pasted per integration.

---

## Decision

Add `import_ref` (nullable, indexed, unique per doc_type) to `CMSDocument`, and introduce a new package
`starlette-cms-gateways` that provides the framework primitives for pulling external service data into
starlette-cms as documents.

**The package is a framework, not a collection of integrations.** It ships `BaseGateway`, `GatewayItem`,
`SyncResult`, `CMSClient`, `JobStore`, `GatewayAdmin`, and a CLI plugin harness. Gateway implementations
(Spotify, iNaturalist, GitHub, etc.) are written by consumers and registered via Python entry points.

---

## API shape

```python
from starlette_cms_gateways import BaseGateway, GatewayItem
from collections.abc import AsyncIterator

class SpotifyLikedSongsGateway(BaseGateway):
    service_name = "spotify_liked_songs"
    block_type = "spotify_liked_song"
    auto_publish = False  # default: create as drafts

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        async for track in spotify_client.iter_liked_songs():
            yield GatewayItem(
                import_ref=f"spotify:liked:{track['id']}",
                slug=f"spotify-liked-{track['id']}",
                body={
                    "track_name": track["name"],
                    "artist_name": track["artists"][0]["name"],
                    "liked_at": track["added_at"],
                },
            )
```

**Incremental sync** — the framework does NOT inject a `since` parameter into `fetch()`. Gateways that need
incremental behaviour read from `self._job_store` (available when a `JobStore` is wired in) and decide what
to do with the cursor themselves:

```python
async def fetch(self) -> AsyncIterator[GatewayItem]:
    since = None
    if self._job_store is not None:
        since = await self._job_store.get_last_synced(self._job_store_key)

    # use `since` however makes sense for your API
    if since is not None:
        params["d1"] = since.date().isoformat()
```

`BaseGateway.__init__` accepts `job_store` and `job_store_key` keyword arguments. `GatewayAdmin` wires
these automatically when constructing gateways for admin-triggered syncs.

CLI usage (gateway registered via entry point):

```bash
gateways sync spotify-liked-songs \
    --cms-url https://cms.example.com \
    --api-key $CMS_API_KEY

gateways list
```

---

## Rationale

**`import_ref` belongs on `CMSDocument`, not in gateway-layer metadata.** Storing the external ID in the
document `meta` JSONField would require a full list scan on every sync to find existing records. A nullable
indexed column supports efficient `WHERE doc_type = ? AND import_ref = ?` lookups. Uniqueness is enforced
at the application layer (409 on collision) rather than as a DB constraint so that NULL values (authored
documents) are permitted without compound-key complexity.

**The gateway worker is a separate process, not embedded in the CMS.** Following ADR 005 (MCP server
architecture), gateway jobs call `POST /api/documents` via HTTP. The CMS remains stateless and serves
only HTTP. A gateway job is a CLI command or cron task — no background thread, no CMS-internal scheduler.

**`auto_publish` is configurable per gateway and defaults to False.** Synced items should require explicit
human approval before appearing publicly. Gateways that want immediate publication set `auto_publish = True`
explicitly on their subclass.

**Cursor management is the gateway's own responsibility.** The framework provides `JobStore.get_last_synced()`
as an opt-in utility, but does not prescribe how gateways use it. A gateway may ignore it, read from a CMS
singleton, use a file, or consult an external store — whatever fits the use case. This decouples the sync
loop from a specific state storage strategy.

**OpenTelemetry is the observability layer.** Each gateway sync run emits an OTel span with `gateway_name`
and item count attributes. `JobStore` is separate operational state — SQLite records used by the admin UI
to display last-sync timestamps and recent job history. These concerns are intentionally separate.

**`JobStore` is optional framework infrastructure, not mandated.** Gateways that don't need admin UI or
incremental sync can use `BaseGateway` with only `cms_client`. The `JobStore` and `job_store_key` params
on `BaseGateway.__init__` are keyword-only and default to `None`.

**`GatewaySyncState` CMS singleton is explicitly not rebuilt.** An earlier draft stored sync state as a
`@block(..., singleton=True)` in the CMS. This was removed: it created a hard coupling between the gateway
framework and the block registry, made the sync state visible in the editor UI (wrong layer), and required
a schema migration to adopt. SQLite operational records in `JobStore` are the correct home for this data.

**Gateway implementations are not shipped with the framework.** Bundling Spotify or iNaturalist integrations
would create optional API-client dependencies that most users don't need and would tie the package release
cycle to upstream API changes. The entry-point plugin system lets consumers publish their own gateway packages
independently.

---

## Alternatives considered

**Store external IDs in the `slug` field.**
Rejected. Slugs are human-readable URL paths used in frontend routes. Encoding `spotify:liked:abc123` as a
slug pollutes the URL namespace and makes the slug field semantically overloaded.

**Store external IDs in `meta` as a JSONField.**
Rejected. Requires a full-collection scan or a JSONField index (not supported uniformly across SQLite and
Postgres). A dedicated column is the correct tool.

**Include built-in Spotify / iNaturalist gateways.**
Rejected. The package is a framework. Bundling specific integrations creates versioning coupling and
encourages treating the package as a content-type registry rather than a framework.

**Add a gateway scheduler inside the CMS.**
Rejected. The CMS is a headless HTTP server — see ADR 005. Gateway scheduling belongs at the infrastructure
layer (cron, GitHub Actions, Celery beat).

**Inject `since: datetime | None` into `fetch()`.**
Rejected. Makes the framework prescriptive about cursor storage strategy. Gateways have wildly different
needs: some filter by datetime, some by a page cursor, some by an event ID, some need no cursor at all.
A single `since` parameter only serves the datetime case and leaks opinionated state management into the
abstract interface. See Design History for the full trail.

**Store sync state as a CMS singleton (`GatewaySyncState`).**
Rejected after prototyping. Creates coupling between framework and block registry, shows operational data
in the editor UI, and requires a schema migration to adopt. Replaced by `JobStore` (SQLite, separate file,
no block registry involvement).

---

## Consequences

**Positive:**
- Any developer can implement a gateway in ~50 lines by subclassing `BaseGateway` and implementing `fetch()`
- `import_ref` is a general-purpose field usable by any code that needs stable external IDs
- `GatewayAdmin` provides a web UI for listing gateways and triggering syncs without writing CLI wrappers
- Incremental sync is available to any gateway running through the admin — no boilerplate in the subclass
- `JobStore` is promotable to top-level namespace so CLI triggers and future MCP surfaces can share it

**Negative / tradeoffs:**
- `CMSDocument` schema migration is required; existing deployments need a schema version bump
- Gateway consumers must manage their own auth credentials and API client setup
- No built-in retry or backoff — the gateway worker must handle transient API errors itself

**Neutral / deferred:**
- Monthly/temporal aggregation gateways are a consumer-level concern — `BaseGateway` supports them
- A `starlette-cms-gateways-contrib` package could ship community-maintained integrations in the future
- `last_synced` display in admin UI currently shows ISO timestamps; relative time ("2 hours ago") is a
  future enhancement

---

## Design History (compressed)

The original 2026-06-19 draft specified `fetch(self, since: datetime | None)` and stored last-sync state
as a `GatewaySyncState` CMS singleton. Three amendments followed:

1. **EPIC-002 STORY-001 (2026-06-28):** Removed `since` from `fetch()`, removed `GatewaySyncState`, removed
   `CMSClient.get_last_synced()` / `save_sync_state()`. Rationale: OTel is the observability layer; gateways
   own their cursor state. The `since` parameter was only one of many possible cursor shapes.

2. **EPIC-002 STORY-002 (2026-06-28):** Changed blocks to mutable by default (`append_only=False`). Added
   `immutable: ClassVar[bool] = False` as a declarative marker for tooling. Rationale: allows post-sync
   annotation via MCP, editor, or API.

3. **EPIC-002 STORY-003 (2026-06-28):** Changed `auto_publish` default from `True` to `False`. Rationale:
   synced items should require explicit human approval — `True` was optimistic for a general-purpose framework.

4. **EPIC-002 follow-up (2026-07-05):** Promoted `JobStore` from `admin/jobstore.py` to
   `starlette_cms_gateways.jobstore` (top-level namespace). Added `get_last_synced()` to `JobStore`. Added
   `job_store` / `job_store_key` params to `BaseGateway.__init__`. `GatewayAdmin` now wires these
   automatically when constructing gateways. Admin UI shows "Last synced" per gateway card, updating live
   after a sync completes. Examples updated to demonstrate the incremental sync pattern.
