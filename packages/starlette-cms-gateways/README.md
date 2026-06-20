# starlette-cms-gateways

Gateway framework for [starlette-cms](https://github.com/ASneakyToast/astraeus) — pull data from external
services into your CMS as documents, with deduplication, incremental sync, and CLI tooling built in.

Part of the [Astraeus](https://github.com/ASneakyToast/astraeus) data platform for Python/Starlette developers.

## Install

```bash
pip install starlette-cms-gateways
```

Optional extras:

```bash
pip install "starlette-cms-gateways[mcp]"   # MCP server tools
```

## Quickstart

Define a block type for your gateway data in your own app:

```python
from starlette_cms.registry import block
from starlette_cms.fields import TextField, URLField

@block("spotify_liked_song", append_only=True)
class SpotifyLikedSongBlock:
    track_name:  str = TextField()
    artist_name: str = TextField()
    spotify_url: str = URLField()
    liked_at:    str = TextField()
```

Implement the gateway:

```python
from starlette_cms_gateways import BaseGateway, GatewayItem
from collections.abc import AsyncIterator
from datetime import datetime

class SpotifyLikedSongsGateway(BaseGateway):
    service_name = "spotify_liked_songs"
    block_type   = "spotify_liked_song"
    auto_publish = True

    async def fetch(self, since: datetime | None) -> AsyncIterator[GatewayItem]:
        async for track in self.spotify.iter_liked_songs(after=since):
            yield GatewayItem(
                import_ref=f"spotify:liked:{track['id']}",
                slug=f"spotify-liked-{track['id']}",
                body={
                    "track_name":  track["name"],
                    "artist_name": track["artists"][0]["name"],
                    "spotify_url": track["external_urls"]["spotify"],
                    "liked_at":    track["added_at"],
                },
            )
```

Register it as an entry point:

```toml
# pyproject.toml
[project.entry-points."starlette_cms_gateways.gateways"]
spotify-liked-songs = "myapp.gateways.spotify:SpotifyLikedSongsGateway"
```

Sync:

```bash
gateways sync spotify-liked-songs \
    --cms-url https://cms.example.com \
    --api-key $CMS_API_KEY
```

## How it works

The framework handles everything except the external API call:

- **Deduplication** — each `GatewayItem` carries an `import_ref` (stable external ID). On sync, the
  framework queries the CMS for an existing document with that `import_ref` and decides create / update /
  skip based on a content hash stored in `meta`.
- **Incremental sync** — the framework persists a `GatewaySyncState` singleton in your CMS after each run.
  On the next run it passes `since` to your `fetch()` so you only pull new/changed items.
- **Sync state** — last-synced timestamps and item counts are stored as a CMS singleton document, queryable
  via the CMS API or MCP tools.

## CLI

```bash
gateways list                             # list installed gateways
gateways sync <name> --cms-url ... \      # run a sync
    --api-key ...
gateways status --cms-url ... \           # show last sync state for all gateways
    --api-key ...
```

## `BaseGateway` reference

| Attribute | Type | Description |
|---|---|---|
| `service_name` | `ClassVar[str]` | Unique service identifier (used in sync state key) |
| `block_type` | `ClassVar[str]` | CMS block type name for synced documents |
| `auto_publish` | `ClassVar[bool]` | Publish documents immediately on sync (default `True`) |

| Method | Signature | Description |
|---|---|---|
| `fetch` | `(since: datetime \| None) → AsyncIterator[GatewayItem]` | **Implement this.** Yield items from the external service. |
| `sync` | `(full_refresh: bool = False) → SyncResult` | Framework-provided. Calls `fetch()` and upserts all items. |

## `GatewayItem` reference

| Field | Type | Description |
|---|---|---|
| `import_ref` | `str` | Stable external ID, e.g. `"spotify:liked:abc123"` |
| `slug` | `str` | URL-safe CMS slug, e.g. `"spotify-liked-abc123"` |
| `body` | `dict` | Block field values |
| `published` | `bool` | Override per-item (default: gateway's `auto_publish`) |

## Examples

See [`examples/`](./examples/) for full implementations:

- [`examples/spotify_liked_songs/`](./examples/spotify_liked_songs/) — Spotify liked songs with the Spotipy library
- [`examples/inaturalist_outings/`](./examples/inaturalist_outings/) — iNaturalist observations grouped into outings

## Requirements

- Python 3.12+
- starlette-cms ≥ 0.5 (with `import_ref` support — schema version 2+)

## License

MIT
