"""
Initial schema snapshot for starlette-cms.

Captures the full schema of CMSDocument, CMSMeta, and CMSWebhook as of
starlette-cms 0.5.0.

- **Existing installs (EC2):** run with ``piccolo migrations forwards --fake starlette_cms``
  to register the migration as applied without re-executing the DDL.
- **Fresh installs:** run normally — this migration creates all three tables.
"""

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import JSON, Boolean, Text, Timestamptz, Varchar

ID = "2026-06-28T00:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "Initial schema snapshot: CMSDocument, CMSMeta, CMSWebhook"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    # ------------------------------------------------------------------
    # CMSDocument
    # ------------------------------------------------------------------
    manager.add_table("CMSDocument", tablename="cms_document")

    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": False,
            "primary_key": True,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="doc_type",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="slug",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 500,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="body",
        column_class_name="JSON",
        column_class=JSON,
        params={
            "default": "{}",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="meta",
        column_class_name="JSON",
        column_class=JSON,
        params={
            "default": "{}",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="created_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="updated_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="published",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="published_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="singleton_status",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 16,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="import_ref",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 256,
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": True,
        },
    )

    # ------------------------------------------------------------------
    # CMSMeta
    # ------------------------------------------------------------------
    manager.add_table("CMSMeta", tablename="cms_meta")

    manager.add_column(
        table_class_name="CMSMeta",
        tablename="cms_meta",
        column_name="id",
        column_class_name="Serial",
        params={
            "null": False,
            "primary_key": True,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSMeta",
        tablename="cms_meta",
        column_name="key",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 255,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": True,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSMeta",
        tablename="cms_meta",
        column_name="value",
        column_class_name="Text",
        column_class=Text,
        params={
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    # ------------------------------------------------------------------
    # CMSWebhook
    # ------------------------------------------------------------------
    manager.add_table("CMSWebhook", tablename="cms_webhook")

    manager.add_column(
        table_class_name="CMSWebhook",
        tablename="cms_webhook",
        column_name="id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": False,
            "primary_key": True,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSWebhook",
        tablename="cms_webhook",
        column_name="url",
        column_class_name="Text",
        column_class=Text,
        params={
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSWebhook",
        tablename="cms_webhook",
        column_name="events",
        column_class_name="JSON",
        column_class=JSON,
        params={
            "default": "{}",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSWebhook",
        tablename="cms_webhook",
        column_name="created_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSWebhook",
        tablename="cms_webhook",
        column_name="active",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": True,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    # Note: a composite (doc_type, import_ref) index would be ideal for
    # gateway sync lookups. Piccolo's add_raw() fires *before* table creation,
    # so we cannot add it here. The single-column index on import_ref (set via
    # index=True above) is sufficient for current query patterns. A follow-up
    # migration can add the composite index once cms_document exists.

    return manager
