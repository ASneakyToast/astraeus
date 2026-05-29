"""Catalog — async SQLite interface for asset metadata."""

from __future__ import annotations

import aiosqlite

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS assets (
    key             TEXT PRIMARY KEY,
    content_hash    TEXT NOT NULL,
    bucket          TEXT NOT NULL,
    original_key    TEXT,
    filename        TEXT NOT NULL,
    content_type    TEXT NOT NULL,
    size            INTEGER NOT NULL,
    width           INTEGER,
    height          INTEGER,
    alt_text        TEXT,
    tags            TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS derivatives (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_key    TEXT NOT NULL REFERENCES assets(key),
    iiif_params     TEXT NOT NULL,
    derivative_key  TEXT NOT NULL,
    width           INTEGER,
    height          INTEGER,
    format          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(original_key, iiif_params)
);

CREATE TABLE IF NOT EXISTS asset_references (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_key       TEXT NOT NULL REFERENCES assets(key),
    host_model      TEXT NOT NULL,
    host_id         TEXT NOT NULL,
    field_name      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(asset_key, host_model, host_id, field_name)
);

CREATE INDEX IF NOT EXISTS idx_references_host ON asset_references(host_model, host_id);
CREATE INDEX IF NOT EXISTS idx_references_asset ON asset_references(asset_key);
"""


class Catalog:

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database connection and ensure schema exists."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(SCHEMA_SQL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    # TODO: implement insert_asset, get_asset, list_assets, update_asset,
    #       delete_asset, get_or_create_derivative, insert_derivative,
    #       set_references, remove_references, find_orphans, export_csv
