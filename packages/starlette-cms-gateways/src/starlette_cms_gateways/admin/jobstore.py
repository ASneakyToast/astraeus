"""
Lightweight SQLite job store for gateway sync runs.

Uses stdlib ``sqlite3`` via ``asyncio.to_thread`` — no extra dependencies.
The database is a single file (default: ``gateway_jobs.db`` in the current
working directory) containing one table: ``gateway_sync_jobs``.

This is intentionally separate from the CMS document store.  Sync job records
are operational infrastructure — not content — and do not belong in the block
registry or the editor UI.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS gateway_sync_jobs (
    run_id       TEXT PRIMARY KEY,
    gateway_name TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'running',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    created      INTEGER DEFAULT 0,
    updated      INTEGER DEFAULT 0,
    skipped      INTEGER DEFAULT 0,
    errors       TEXT DEFAULT '[]',
    error        TEXT DEFAULT ''
)
"""


class JobStore:
    """
    Async wrapper around a SQLite database for sync job records.

    :param path: Path to the SQLite database file.  Created on first use.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialised = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    async def init(self) -> None:
        """Create the table if it doesn't exist yet. Safe to call multiple times."""
        if not self._initialised:
            await asyncio.to_thread(self._ensure_table)
            self._initialised = True

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _insert(self, run_id: str, gateway_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_sync_jobs
                    (run_id, gateway_name, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (run_id, gateway_name, datetime.now(UTC).isoformat()),
            )
            conn.commit()

    async def create(self, run_id: str, gateway_name: str) -> None:
        """Insert a new job record with status='running'."""
        await self.init()  # no-op after first call
        await asyncio.to_thread(self._insert, run_id, gateway_name)

    def _finish(
        self,
        run_id: str,
        *,
        status: str,
        created: int = 0,
        updated: int = 0,
        skipped: int = 0,
        errors: list | None = None,
        error: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE gateway_sync_jobs
                SET status      = ?,
                    finished_at = ?,
                    created     = ?,
                    updated     = ?,
                    skipped     = ?,
                    errors      = ?,
                    error       = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    datetime.now(UTC).isoformat(),
                    created,
                    updated,
                    skipped,
                    json.dumps(errors or []),
                    error,
                    run_id,
                ),
            )
            conn.commit()

    async def finish(
        self,
        run_id: str,
        *,
        status: str,
        created: int = 0,
        updated: int = 0,
        skipped: int = 0,
        errors: list | None = None,
        error: str = "",
    ) -> None:
        """Update a job record with its final status and result counts."""
        await asyncio.to_thread(
            self._finish,
            run_id,
            status=status,
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
            error=error,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM gateway_sync_jobs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    async def get(self, run_id: str) -> dict[str, Any] | None:
        """Return the job record for *run_id*, or ``None`` if not found."""
        await self.init()
        return await asyncio.to_thread(self._get, run_id)

    def _list_for_gateway(self, gateway_name: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM gateway_sync_jobs
                WHERE gateway_name = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (gateway_name, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def list_for_gateway(self, gateway_name: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent *limit* jobs for *gateway_name*."""
        await self.init()
        return await asyncio.to_thread(self._list_for_gateway, gateway_name, limit)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    # Deserialise the errors JSON column
    errors_raw = d.get("errors") or "[]"
    try:
        d["errors"] = json.loads(errors_raw)
    except (json.JSONDecodeError, TypeError):
        d["errors"] = []
    # Build a nested result dict when the job is finished
    if d.get("status") in ("done", "error"):
        d["result"] = {
            "created": d.pop("created", 0),
            "updated": d.pop("updated", 0),
            "skipped": d.pop("skipped", 0),
            "errors": d.pop("errors", []),
        }
    else:
        d.pop("created", None)
        d.pop("updated", None)
        d.pop("skipped", None)
        d.pop("errors", None)
    d.pop("error", None)  # only include if non-empty
    return d
