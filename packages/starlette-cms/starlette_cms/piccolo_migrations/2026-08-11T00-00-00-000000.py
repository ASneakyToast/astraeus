"""
Migration: add CMSDocumentVersion table and reviewed_at column on CMSChangeset.

Creates:
- ``cms_document_version`` — snapshot of document body at publish/revert time
- ``reviewed_at`` column on ``cms_changeset`` — tracks when a changeset entered review
"""

from piccolo.apps.migrations.auto import MigrationManager
from piccolo.columns import Integer, JSON, Timestamptz, Varchar

ID = "2026-08-11T00:00:00:000000"
VERSION = "1.0"
DESCRIPTION = "Add CMSDocumentVersion table and reviewed_at on CMSChangeset"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="starlette_cms",
        description=DESCRIPTION,
    )

    # ------------------------------------------------------------------
    # CMSDocumentVersion
    # ------------------------------------------------------------------
    manager.add_table("CMSDocumentVersion", tablename="cms_document_version")

    manager.add_column(
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
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
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
        column_name="document_id",
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
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
        column_name="version",
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
    manager.add_column(
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
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
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
        column_name="action",
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
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
        column_name="changeset_id",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 36,
            "default": "",
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )
    manager.add_column(
        table_class_name="CMSDocumentVersion",
        tablename="cms_document_version",
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

    # ------------------------------------------------------------------
    # CMSChangeset — add reviewed_at column
    # ------------------------------------------------------------------
    manager.add_column(
        table_class_name="CMSChangeset",
        tablename="cms_changeset",
        column_name="reviewed_at",
        column_class_name="Timestamptz",
        column_class=Timestamptz,
        params={
            "null": True,
            "primary_key": False,
            "unique": False,
            "index": False,
        },
    )

    return manager
