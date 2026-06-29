"""Tests for the Piccolo-native migration system."""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import tempfile
import types
from contextlib import contextmanager

import pytest
from piccolo.apps.migrations.commands.forwards import ForwardsMigrationManager
from piccolo.apps.migrations.tables import Migration
from piccolo.engine.sqlite import SQLiteEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _temp_engine() -> tuple[SQLiteEngine, str]:
    """Return a (engine, db_path) pair for a fresh temp SQLite file."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return SQLiteEngine(path=f.name), f.name


async def _set_engine(engine: SQLiteEngine) -> None:
    """Assign engine to all CMS table classes and the Migration tracker."""
    from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

    CMSDocument._meta.db = engine
    CMSMeta._meta.db = engine
    CMSWebhook._meta.db = engine
    Migration._meta.db = engine


@contextmanager
def _piccolo_conf_ctx(engine: SQLiteEngine):
    """
    Temporarily inject a piccolo_conf module into sys.modules so that
    MigrationManager.run() can find the engine via engine_finder().

    Piccolo's engine_finder() imports piccolo_conf and reads its DB attribute.
    """
    from piccolo.conf.apps import AppRegistry

    from starlette_cms.piccolo_app import APP_CONFIG

    mock_conf = types.ModuleType("piccolo_conf")
    mock_conf.DB = engine  # type: ignore[attr-defined]
    mock_conf.APP_REGISTRY = AppRegistry(apps=["starlette_cms.piccolo_app"])  # type: ignore[attr-defined]

    old = sys.modules.get("piccolo_conf")
    sys.modules["piccolo_conf"] = mock_conf
    try:
        yield
    finally:
        if old is None:
            sys.modules.pop("piccolo_conf", None)
        else:
            sys.modules["piccolo_conf"] = old


# ---------------------------------------------------------------------------
# 1. APP_CONFIG sanity checks
# ---------------------------------------------------------------------------


def test_piccolo_app_config():
    from starlette_cms.piccolo_app import APP_CONFIG

    assert APP_CONFIG.app_name == "starlette_cms"
    migrations_folder = APP_CONFIG.migrations_folder_path
    assert migrations_folder.exists(), f"migrations folder does not exist: {migrations_folder}"
    py_files = [
        p for p in migrations_folder.iterdir()
        if p.suffix == ".py" and p.stem != "__init__"
    ]
    assert py_files, "No migration .py files found in piccolo_migrations/"


# ---------------------------------------------------------------------------
# 2. Initial migration module is well-formed
# ---------------------------------------------------------------------------


def test_initial_migration_module():
    mod = importlib.import_module(
        "starlette_cms.piccolo_migrations.2026-06-28T00-00-00-000000"
    )
    assert hasattr(mod, "ID"), "migration module must define ID"
    assert hasattr(mod, "forwards"), "migration module must define forwards()"
    assert inspect.iscoroutinefunction(mod.forwards), "forwards must be a coroutine function"


# ---------------------------------------------------------------------------
# 3. forwards --fake on an existing DB
# ---------------------------------------------------------------------------


async def test_forwards_fake_on_existing_db():
    """
    Running forwards with fake=True on an existing DB records the migration row
    without re-creating the tables.
    """
    from starlette_cms.piccolo_app import APP_CONFIG
    from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

    engine, db_path = _temp_engine()
    try:
        await _set_engine(engine)

        # Pre-create tables (simulating an existing install)
        await CMSDocument.create_table(if_not_exists=True)
        await CMSMeta.create_table(if_not_exists=True)
        await CMSWebhook.create_table(if_not_exists=True)
        await Migration.create_table(if_not_exists=True)

        # No migration rows yet
        assert await Migration.count().run() == 0

        # --fake: piccolo skips MigrationManager.run() entirely, so no
        # engine_finder() is called — safe to run without piccolo_conf.
        runner = ForwardsMigrationManager(app_name="starlette_cms", fake=True)
        await runner.run_migrations(APP_CONFIG)

        # Migration row should now be recorded
        assert await Migration.count().run() == 1
        row = (await Migration.select().run())[0]
        assert row["app_name"] == "starlette_cms"
        assert "2026-06-28" in row["name"]
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# 4. forwards on a fresh DB creates tables
# ---------------------------------------------------------------------------


async def test_forwards_on_fresh_db():
    """
    Running forwards on an empty DB creates all tables and records the
    migration row.
    """
    from starlette_cms.piccolo_app import APP_CONFIG
    from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

    engine, db_path = _temp_engine()
    try:
        await _set_engine(engine)
        # Only create the Migration tracker (piccolo's own bookkeeping table)
        await Migration.create_table(if_not_exists=True)

        runner = ForwardsMigrationManager(app_name="starlette_cms", fake=False)
        with _piccolo_conf_ctx(engine):
            await runner.run_migrations(APP_CONFIG)

        # All CMS tables should now exist — verify by counting rows
        # (will raise if the table doesn't exist)
        from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

        assert await CMSDocument.count().run() == 0
        assert await CMSMeta.count().run() == 0
        assert await CMSWebhook.count().run() == 0

        # Migration row recorded
        assert await Migration.count().run() == 1
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# 5. forwards is idempotent
# ---------------------------------------------------------------------------


async def test_forwards_idempotent():
    """
    Running forwards twice produces exactly one migration row and no error.
    """
    from starlette_cms.piccolo_app import APP_CONFIG

    engine, db_path = _temp_engine()
    try:
        await _set_engine(engine)
        await Migration.create_table(if_not_exists=True)

        with _piccolo_conf_ctx(engine):
            runner = ForwardsMigrationManager(app_name="starlette_cms", fake=False)
            await runner.run_migrations(APP_CONFIG)

            # Run again — should be a no-op
            runner2 = ForwardsMigrationManager(app_name="starlette_cms", fake=False)
            await runner2.run_migrations(APP_CONFIG)

        assert await Migration.count().run() == 1
    finally:
        os.unlink(db_path)
