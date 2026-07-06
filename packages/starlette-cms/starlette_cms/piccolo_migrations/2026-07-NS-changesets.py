"""
Migration: add CMSChangeset and CMSChangesetDocument tables (Phase NS-1C).

Creates two new tables:
- ``cms_changeset``          — named group of documents for atomic publish
- ``cms_changeset_document`` — join table linking documents to changesets
"""

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import Boolean, Timestamptz, Varchar

ID = "2026-07-05T01:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "Add CMSChangeset and CMSChangesetDocument tables for Phase NS-1C"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    # ------------------------------------------------------------------
    # CMSChangeset
    # ------------------------------------------------------------------
    manager.add_table("CMSChangeset", tablename="cms_changeset")

    manager.add_column(
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
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
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
        column_name="title",
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
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
        column_name="status",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 16,
            "default": "open",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
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
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
        column_name="publish_at",
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
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
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

    # ------------------------------------------------------------------
    # CMSChangesetDocument
    # ------------------------------------------------------------------
    manager.add_table("CMSChangesetDocument", tablename="cms_changeset_document")

    manager.add_column(
        table_class_name="CMSChangesetDocument",
        tablename="cms_changeset_document",
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
        table_class_name="CMSChangesetDocument",
        tablename="cms_changeset_document",
        column_name="changeset_id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": True,
        },
    )
    manager.add_column(
        table_class_name="CMSChangesetDocument",
        tablename="cms_changeset_document",
        column_name="document_id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSChangesetDocument",
        tablename="cms_changeset_document",
        column_name="added_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    return manager


async def backwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )
    manager.drop_table("CMSChangeset", tablename="cms_changeset")
    manager.drop_table("CMSChangesetDocument", tablename="cms_changeset_document")
    return manager
