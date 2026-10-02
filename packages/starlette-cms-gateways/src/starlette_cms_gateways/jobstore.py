"""
SQLite store for what a gateway remembers between runs.

Uses stdlib ``sqlite3`` via ``asyncio.to_thread`` — no extra dependencies.
Two tables: ``gateway_sync_jobs`` (run history) and ``gateway_cursors`` (the
sync cursor).

In a deployment the file is the CMS's own database (``GatewayAdmin`` defaults
to it): that is the one file that is persistent and backed up, so the cursor
survives restarts and exists exactly once. The tables sit beside the CMS's and
never appear in the block registry or the editor UI. Only the CMS process opens
the file; workers elsewhere go through the gateway API
(:class:`~starlette_cms_gateways.state.RemoteSyncState`).

Every connection sets WAL and a busy timeout, so a write here and a write by
the CMS wait for each other instead of failing with "database is locked".
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUSY_TIMEOUT_MS = 10_000

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
    error        TEXT DEFAULT '',
    deferred     TEXT DEFAULT '[]',
    range        TEXT DEFAULT ''
)
"""

# Columns added after the first release; added to a file that predates them.
_JOB_COLUMNS = {"deferred": "TEXT DEFAULT '[]'", "range": "TEXT DEFAULT ''"}

_CREATE_CURSORS = """
CREATE TABLE IF NOT EXISTS gateway_cursors (
    gateway_name TEXT PRIMARY KEY,
    cursor       TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
"""


class JobStore:
    """
    Async wrapper around a SQLite database for sync state: job records and the
    sync cursor. Implements
    :class:`~starlette_cms_gateways.state.SyncState`.

    :param path: Path to the SQLite database file.  Created on first use.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._initialised = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection: committed and *closed* on exit.

        (``with sqlite3.connect()`` alone commits but leaves the connection open.)
        """
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            try:
                conn.execute("PRAGMA journal_mode=WAL")  # persistent; the CMS sets it too
            except sqlite3.OperationalError:
                pass  # in-memory or read-only: carry on
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_table(self) -> None:
        with self._connect() as conn:
            conn.execute(_CREATE_TABLE)
            conn.execute(_CREATE_CURSORS)
            have = {r["name"] for r in conn.execute("PRAGMA table_info(gateway_sync_jobs)")}
            for column, ddl in _JOB_COLUMNS.items():
                if column not in have:
                    conn.execute(f"ALTER TABLE gateway_sync_jobs ADD COLUMN {column} {ddl}")

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
        deferred: list | None = None,
        range: dict | None = None,  # noqa: A002
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
                    error       = ?,
                    deferred    = ?,
                    range       = ?
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
                    json.dumps(deferred or []),
                    json.dumps(range) if range else "",
                    run_id,
                ),
            )

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
        deferred: list | None = None,
        range: dict | None = None,  # noqa: A002
    ) -> None:
        """Update a job record with its final status and result counts."""
        await self.init()
        await asyncio.to_thread(
            self._finish,
            run_id,
            status=status,
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
            error=error,
            deferred=deferred,
            range=range,
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

    def _get_last_synced_sync(self, key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT finished_at FROM gateway_sync_jobs
                WHERE gateway_name = ? AND status = 'done'
                ORDER BY started_at DESC LIMIT 1
                """,
                (key,),
            ).fetchone()
        if row is None or row["finished_at"] is None:
            return None
        return datetime.fromisoformat(row["finished_at"])

    async def get_last_synced(self, key: str) -> datetime | None:
        """
        Return the ``finished_at`` datetime of the most recent ``status='done'``
        job for *key* (gateway name or service name), or ``None``.

        For **display** ("Last synced" in the admin UI). It is not a cursor: it is
        when a run *finished*, and a run is ``done`` even when items failed. Use
        :meth:`get_cursor`, through ``BaseGateway.resolve_window()``, to decide what
        to fetch.
        """
        await self.init()
        return await asyncio.to_thread(self._get_last_synced_sync, key)

    # ------------------------------------------------------------------
    # Sync cursor
    #
    # The cursor is the start time of the last run that did not raise, kept
    # apart from the job history on purpose: a job can finish with status 'done'
    # and still have failed items, and ``finished_at`` is when the run ended, not
    # the moment up to which the source had been read. A lost cursor is safe —
    # the next run just covers everything.
    # ------------------------------------------------------------------

    def _get_cursor_sync(self, key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cursor FROM gateway_cursors WHERE gateway_name = ?", (key,)
            ).fetchone()
        return datetime.fromisoformat(row["cursor"]) if row else None

    async def get_cursor(self, key: str) -> datetime | None:
        """Return the stored sync cursor for *key*, or ``None`` if there is none."""
        await self.init()
        return await asyncio.to_thread(self._get_cursor_sync, key)

    def _set_cursor_sync(self, key: str, cursor: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO gateway_cursors (gateway_name, cursor, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(gateway_name) DO UPDATE
                    SET cursor = excluded.cursor, updated_at = excluded.updated_at
                """,
                (key, cursor.isoformat(), datetime.now(UTC).isoformat()),
            )

    async def set_cursor(self, key: str, cursor: datetime) -> None:
        """Store *cursor* as the point up to which *key* has been synced."""
        await self.init()
        await asyncio.to_thread(self._set_cursor_sync, key, cursor)


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
    deferred_raw = d.pop("deferred", None) or "[]"
    try:
        deferred = json.loads(deferred_raw)
    except (json.JSONDecodeError, TypeError):
        deferred = []
    range_raw = d.pop("range", None) or ""
    try:
        range_ = json.loads(range_raw) if range_raw else None
    except (json.JSONDecodeError, TypeError):
        range_ = None
    # Build a nested result dict when the job is finished
    if d.get("status") in ("done", "error"):
        d["result"] = {
            "created": d.pop("created", 0),
            "updated": d.pop("updated", 0),
            "skipped": d.pop("skipped", 0),
            "deferred": deferred,
            "errors": d.pop("errors", []),
            "range": range_,
        }
    else:
        d.pop("created", None)
        d.pop("updated", None)
        d.pop("skipped", None)
        d.pop("errors", None)
    if not d.get("error"):
        d.pop("error", None)  # only include if non-empty
    return d
