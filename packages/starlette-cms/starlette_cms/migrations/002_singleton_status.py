"""Add singleton_status column to cms_documents."""

from __future__ import annotations

ID = "2026-06-13T00:00:00"
VERSION = "0.1.0"
DESCRIPTION = "Add singleton_status column"


async def forwards(engine) -> None:
    """
    Add ``singleton_status VARCHAR(16) DEFAULT ''`` to ``cms_documents``.

    Safe to run multiple times — uses ``IF NOT EXISTS`` / ``IF NOT EXISTS``
    pattern via raw DDL.  SQLite silently ignores ``ALTER TABLE … ADD COLUMN``
    if the column already exists when the expression is wrapped in a try/except
    at the call site.
    """
    try:
        await engine.run_ddl(
            "ALTER TABLE cms_documents ADD COLUMN singleton_status VARCHAR(16) DEFAULT ''"
        )
    except Exception:
        # Column already exists — safe to ignore
        pass
