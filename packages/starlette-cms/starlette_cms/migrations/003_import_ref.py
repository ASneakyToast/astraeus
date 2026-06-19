"""Add import_ref column to cms_documents."""

from __future__ import annotations

ID = "2026-06-19T00:00:00"
VERSION = "0.5.0"
DESCRIPTION = "Add import_ref column for gateway deduplication"


async def forwards(engine) -> None:
    """
    Add ``import_ref VARCHAR(256) NULL`` to ``cms_documents`` and create an
    index on ``(doc_type, import_ref)`` for efficient deduplication lookups.

    Safe to run multiple times — column add is wrapped in a try/except, and
    the index creation uses ``IF NOT EXISTS``.
    """
    try:
        await engine.run_ddl(
            "ALTER TABLE cms_documents ADD COLUMN import_ref VARCHAR(256) NULL"
        )
    except Exception:
        # Column already exists — safe to ignore
        pass

    try:
        await engine.run_ddl(
            "CREATE INDEX IF NOT EXISTS idx_cms_documents_import_ref "
            "ON cms_documents (doc_type, import_ref)"
        )
    except Exception:
        pass
