"""
Add draft_body and draft_version columns to CMSDocument.

Phase NS-1A: dual-state (draft/published) document support.

- draft_body: JSON column, nullable. NULL = no unpublished edits. Non-NULL =
  working draft that has not yet been promoted to body via publish.
- draft_version: Integer column, default 0. Incremented on each PATCH that
  writes to draft_body. Reset to 0 on publish or discard-draft.

Note on the partial index:
  A partial index ``ON cms_document (id) WHERE draft_body IS NOT NULL`` would
  speed up ``?has_draft=true`` list queries. However, Piccolo's ``add_raw()``
  fires *before* ``_run_add_columns()``, so we cannot create that index inside
  this migration — the column would not exist yet. Add it manually on existing
  deployments after running this migration::

    CREATE INDEX IF NOT EXISTS idx_cms_document_has_draft
      ON cms_document (id) WHERE draft_body IS NOT NULL;
"""

from __future__ import annotations

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import JSON, Integer

ID = "2026-07-05T00:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "Add draft_body and draft_version to CMSDocument (Phase NS-1A)"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="draft_body",
        column_class_name="JSON",
        column_class=JSON,
        params={
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="draft_version",
        column_class_name="Integer",
        column_class=Integer,
        params={
            "default": 0,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    return manager
