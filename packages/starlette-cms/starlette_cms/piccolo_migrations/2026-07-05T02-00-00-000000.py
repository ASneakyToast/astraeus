"""
Phase NS-2 migration: WebSocket collaborative editing schema.

Creates:
  - ``cms_step`` table — persisted ProseMirror steps for history and rewind

Note: ``draft_body`` and ``draft_version`` columns on ``cms_document`` are
managed by the NS-1A migration (2026-07-NS-draft-body.py). This migration
only creates the step table.

Note on the composite index:
  Piccolo's ``add_raw()`` fires *before* table creation, so we cannot add a
  composite index within the migration itself.  The index should be applied
  manually after this migration runs:

      CREATE INDEX IF NOT EXISTS idx_cms_step_doc_version
          ON cms_step (document_id, version);
"""

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import Integer, Text, Timestamptz, Varchar

ID = "2026-07-05T02:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "NS-2: create cms_step table for ProseMirror collab history"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    manager.add_table("CMSStep", tablename="cms_step")

    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="id",
        column_class_name="Serial",
        params={"null": False, "primary_key": True, "unique": False, "index": False},
    )
    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="document_id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={"length": 36, "default": "", "null": False, "primary_key": False, "unique": False, "index": True},
    )
    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="client_id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={"length": 36, "default": "", "null": False, "primary_key": False, "unique": False, "index": False},
    )
    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="version",
        column_class_name="Integer",
        column_class=Integer,
        params={"default": 0, "null": False, "primary_key": False, "unique": False, "index": False},
    )
    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="step_data",
        column_class_name="Text",
        column_class=Text,
        params={"default": "", "null": False, "primary_key": False, "unique": False, "index": False},
    )
    manager.add_column(
        table_class_name="CMSStep",
        tablename="cms_step",
        column_name="created_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={"null": False, "primary_key": False, "unique": False, "index": False},
    )

    return manager


async def backwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=f"Reverse: {DESCRIPTION}",
    )
    manager.drop_table(class_name="CMSStep", tablename="cms_step")
    return manager
