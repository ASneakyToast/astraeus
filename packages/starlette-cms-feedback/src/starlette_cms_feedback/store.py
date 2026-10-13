"""
SQLite store for feedback reports.

Uses stdlib ``sqlite3`` via ``asyncio.to_thread`` — no extra dependencies, the
same approach as the gateway ``JobStore``.

Reports live in their own database file rather than as CMS documents. The CMS
document API is public-read by default (``read_auth=False``) and has no
draft/published gate on reads, so a report stored there would be readable by
anyone. Here the only way in is the auth-checked API in
:mod:`starlette_cms_feedback.api`.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from starlette_cms_feedback.models import (
    FeedbackCreate,
    FeedbackKind,
    FeedbackReport,
    FeedbackStatus,
    FeedbackUpdate,
)

BUSY_TIMEOUT_MS = 10_000
MAX_LIMIT = 200

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS feedback_reports (
    id                 TEXT PRIMARY KEY,
    kind               TEXT NOT NULL,
    status             TEXT NOT NULL,
    severity           TEXT,
    component          TEXT,
    title              TEXT NOT NULL,
    description        TEXT NOT NULL,
    steps_to_reproduce TEXT,
    expected           TEXT,
    actual             TEXT,
    environment        TEXT,
    reporter           TEXT,
    triage_notes       TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
)
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS feedback_reports_status_created
    ON feedback_reports (status, created_at DESC)
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FeedbackStore:
    """
    Async wrapper around a SQLite database of feedback reports.

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
        """A short-lived connection: committed and *closed* on exit."""
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
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
            conn.execute(_CREATE_INDEX)

    async def init(self) -> None:
        """Create the table if it doesn't exist yet. Safe to call multiple times."""
        if not self._initialised:
            await asyncio.to_thread(self._ensure_table)
            self._initialised = True

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def _insert(self, data: FeedbackCreate) -> FeedbackReport:
        now = _now()
        report = FeedbackReport(
            **data.model_dump(),
            created_at=now,
            id=uuid.uuid4().hex,
            status=FeedbackStatus.NEW,
            updated_at=now,
        )
        row = report.model_dump(mode="json")
        columns = ", ".join(row)
        placeholders = ", ".join(f":{name}" for name in row)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO feedback_reports ({columns}) VALUES ({placeholders})",  # noqa: S608 — column names come from the model, not input
                row,
            )
        return report

    async def create(self, data: FeedbackCreate) -> FeedbackReport:
        """File a new report. It always starts as ``new``."""
        await self.init()
        return await asyncio.to_thread(self._insert, data)

    def _update(self, report_id: str, changes: dict[str, str]) -> bool:
        assignments = ", ".join(f"{name} = :{name}" for name in changes)
        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE feedback_reports SET {assignments}, updated_at = :updated_at "  # noqa: S608 — column names come from the model, not input
                "WHERE id = :id",
                {**changes, "id": report_id, "updated_at": _now()},
            )
            return cursor.rowcount > 0

    async def update(self, report_id: str, data: FeedbackUpdate) -> FeedbackReport | None:
        """
        Apply triage changes to a report.

        Only fields present in the request change; ``None`` for a field that
        was sent clears it, an omitted field is left alone.
        Returns ``None`` if no report has *report_id*.
        """
        await self.init()
        changes = data.model_dump(mode="json", exclude_unset=True)
        if changes:
            found = await asyncio.to_thread(self._update, report_id, changes)
            if not found:
                return None
        return await self.get(report_id)

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _get(self, report_id: str) -> FeedbackReport | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM feedback_reports WHERE id = ?", (report_id,)
            ).fetchone()
        return FeedbackReport(**dict(row)) if row else None

    async def get(self, report_id: str) -> FeedbackReport | None:
        """Return the report with *report_id*, or ``None`` if not found."""
        await self.init()
        return await asyncio.to_thread(self._get, report_id)

    def _list(
        self,
        *,
        component: str | None,
        kind: FeedbackKind | None,
        limit: int,
        offset: int,
        status: FeedbackStatus | None,
    ) -> tuple[list[FeedbackReport], int]:
        clauses: list[str] = []
        params: list[str] = []
        for column, value in (("component", component), ("kind", kind), ("status", status)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(str(value))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM feedback_reports {where}",  # noqa: S608 — clauses are fixed strings
                params,
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM feedback_reports {where} "  # noqa: S608 — clauses are fixed strings
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [FeedbackReport(**dict(r)) for r in rows], total

    async def list_reports(
        self,
        *,
        component: str | None = None,
        kind: FeedbackKind | None = None,
        limit: int = 50,
        offset: int = 0,
        status: FeedbackStatus | None = None,
    ) -> tuple[list[FeedbackReport], int]:
        """
        Return ``(reports, total)``, newest first.

        *total* counts every match ignoring *limit* and *offset*.
        """
        await self.init()
        return await asyncio.to_thread(
            self._list,
            component=component,
            kind=kind,
            limit=max(1, min(limit, MAX_LIMIT)),
            offset=max(0, offset),
            status=status,
        )
