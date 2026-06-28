# ADR 015 — starlette-cms-gateways: external service gateway framework

**Status:** Accepted
**Date:** 2026-06-19
**Informed by:** `docs/use-cases/personal-site-joellithgow.md`

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
track-last-synced, expose via CLI. This repeating pattern belongs in a reusable package rather than copy-pasted
per integration.

---

## Decision

Add `import_ref` (nullable, indexed, unique per doc_type) to `CMSDocument`, and introduce a new package
`starlette-cms-gateways` that provides the framework primitives for pulling external service data into
starlette-cms as documents.

**The package is a framework, not a collection of integrations.** It ships `BaseGateway`, `GatewayItem`,
`SyncResult`, `CMSClient`, `GatewaySyncState`, and a CLI plugin harness. Gateway implementations
(Spotify, iNaturalist, GitHub, etc.) are written by consumers and registered via Python entry points.

---

## API shape

```python
from starlette_cms_gateways import BaseGateway, GatewayItem

class SpotifyLikedSongsGateway(BaseGateway):
    service_name = "spotify_liked_songs"
    block_type = "spotify_liked_song"
    auto_publish = True

    async def fetch(self, since: datetime | None) -> AsyncIterator[GatewayItem]:
        async for track in spotify_client.iter_liked_songs(after=since):
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

CLI usage (gateway registered via entry point):

```bash
gateways sync spotify-liked-songs \
    --cms-url https://cms.example.com \
    --api-key $CMS_API_KEY

gateways status --cms-url https://cms.example.com --api-key $CMS_API_KEY
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

**`auto_publish` is configurable per gateway.** Liked songs and wildlife observations are personal activity
that can auto-publish. Future gateways (e.g. social media imports) may want a review step. The `auto_publish`
flag on each `BaseGateway` subclass controls this without a central registry setting.

**Sync state is stored as a CMS singleton.** Using `GatewaySyncState` (a `@block(..., singleton=True)`) to
persist last-sync timestamps stores operational metadata in the same database as content. This makes the
sync state visible via the CMS API, queryable by MCP tools, and avoids a separate metadata store.

**Gateway implementations are not shipped with the framework.** Bundling Spotify or iNaturalist integrations
would create optional API-client dependencies that most users don't need and would tie the package release
cycle to upstream API changes. The entry-point plugin system lets consumers publish their own gateway packages
independently (`joellithgow-gateways`, `mysite-gateways`, etc.).

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
encourages treating the package as a content-type registry rather than a framework. Specific gateways
belong in consumer repos or independently published packages.

**Add a gateway scheduler inside the CMS.**
Rejected. The CMS is a headless HTTP server — see ADR 005. Gateway scheduling belongs at the infrastructure
layer (cron, GitHub Actions, Celery beat).

---

## Consequences

**Positive:**
- Any developer can implement a gateway in ~50 lines by subclassing `BaseGateway` and implementing `fetch()`
- Sync state is observable via the CMS API and MCP tools without a separate service
- `import_ref` is a general-purpose field usable by any code that needs stable external IDs, not just gateways

**Negative / tradeoffs:**
- `CMSDocument` schema migration is required; existing deployments need a schema version bump
- Gateway consumers must manage their own auth credentials and API client setup
- No built-in retry or backoff — the gateway worker must handle transient API errors itself

**Neutral / deferred:**
- Monthly/temporal aggregation gateways (e.g. "Spotify monthly liked songs") are a consumer-level concern —
  `BaseGateway` supports them but the framework provides no special aggregation primitives
- A `starlette-cms-gateways-contrib` package could ship community-maintained integrations in the future

---

## Amendment — EPIC-002 STORY-001 (2026-06-28)

`GatewaySyncState` and the `since` parameter have been removed from the framework.

**What was removed:**
- `blocks.py` — `GatewaySyncStateBlock` helper and `register()` function
- `CMSClient.get_last_synced()`, `save_sync_state()`, `get_gateway_status()` methods
- `BaseGateway.sync(full_refresh=...)` — the `full_refresh` parameter
- `BaseGateway.fetch(since: datetime | None)` — the `since` parameter
- CLI `status` and `register-blocks` commands
- MCP `list_gateway_syncs` tool

**Rationale:** OpenTelemetry is now the observability layer for sync runs. Each gateway owns its own
incremental-sync cursor state — the framework should not prescribe how state is stored. Gateways that
need incremental sync can manage a CMS singleton, a file, or an external store themselves. Removing
the built-in state layer simplifies the framework, removes a CMS dependency on `singleton=True` blocks,
and decouples observability from the sync loop.

**Migration:** Subclasses that relied on the `since` parameter must manage their own cursor state.
Remove the `since` argument from `fetch()` implementations and call `register()` / `register-blocks`
from consumer startup code if the `gateway_sync_state` singleton was previously used.

---

## Amendment — EPIC-002 STORY-002 (2026-06-28): mutable by default

Gateway blocks are now **mutable by default** (`append_only=False`).  The previous examples used
`append_only=True` which prevented post-sync annotation.  The new default allows patching synced
documents via MCP, the editor, or the API — adding notes, tags, curated fields, etc.

A new `immutable: ClassVar[bool] = False` attribute on `BaseGateway` serves as a **declarative marker**
for tooling.  Gateways that want audit-trail behaviour set both `append_only=True` on the block and
`immutable = True` on the gateway class.  The CMS enforces `append_only` at the API layer.

---

## Amendment — EPIC-002 STORY-003 (2026-06-28): draft-by-default

`auto_publish` class-level default changed from `True` to `False` in both `BaseGateway`
and `CMSClient.upsert()`.

**Rationale:** Synced items should require explicit human approval before appearing publicly.  The original
default of `True` was optimistic (suited to personal activity feeds), but it is the wrong safe default for
a general-purpose framework.  Gateways that want immediate publication set `auto_publish = True` explicitly
on their subclass — the override is one line and the intent is clear.

**Migration:** Any existing `BaseGateway` subclass that relied on the `True` default must now set
`auto_publish = True` explicitly.
