"""
Migration: add draft_published column to CMSDocument.

Nullable Boolean — tracks pending publish/unpublish state changes that
are applied when a changeset publishes.
"""

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import Boolean

ID = "2026-08-17T00:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "Add draft_published column to CMSDocument"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    manager.add_column(
        table_class_name="CMSDocument",
        tablename="cms_document",
        column_name="draft_published",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": None,
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    return manager
