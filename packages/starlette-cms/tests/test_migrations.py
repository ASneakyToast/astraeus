"""Tests for the migration runner."""

from __future__ import annotations

import os
import tempfile

import pytest
from starlette_cms import CMS, TextField
from starlette_cms.migrations import MigrationError, MigrationRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cms_with_migrations() -> tuple[CMS, str]:
    """Return a CMS + temp db path pre-loaded with two migration steps."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    cms = CMS(database_url=f"sqlite:///{f.name}", auth="none")

    @cms.block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    @cms.migration(from_version="0.1.0", to_version="0.2.0")
    async def m_0_1_to_0_2(db):
        pass  # no-op for testing

    @cms.migration(from_version="0.2.0", to_version="0.3.0")
    async def m_0_2_to_0_3(db):
        pass

    return cms, f.name


# ---------------------------------------------------------------------------
# Chain building — pending()
# ---------------------------------------------------------------------------


def test_pending_empty_when_versions_match():
    cms, db_path = _cms_with_migrations()
    try:
        runner = MigrationRunner(cms)
        chain = runner.pending(current_version="0.2.0", target_version="0.2.0")
        assert chain == []
    finally:
        os.unlink(db_path)


def test_pending_single_step():
    cms, db_path = _cms_with_migrations()
    try:
        runner = MigrationRunner(cms)
        chain = runner.pending(current_version="0.1.0", target_version="0.2.0")
        assert len(chain) == 1
        assert chain[0].from_version == "0.1.0"
        assert chain[0].to_version == "0.2.0"
    finally:
        os.unlink(db_path)


def test_pending_two_steps():
    cms, db_path = _cms_with_migrations()
    try:
        runner = MigrationRunner(cms)
        chain = runner.pending(current_version="0.1.0", target_version="0.3.0")
        assert len(chain) == 2
        assert chain[0].from_version == "0.1.0"
        assert chain[1].from_version == "0.2.0"
        assert chain[1].to_version == "0.3.0"
    finally:
        os.unlink(db_path)


def test_pending_raises_on_broken_chain():
    cms = CMS(database_url="sqlite:///dummy.db", auth="none")

    @cms.migration(from_version="0.1.0", to_version="0.2.0")
    async def m(db):
        pass

    runner = MigrationRunner(cms)
    with pytest.raises(MigrationError, match="No migration registered from"):
        runner.pending(current_version="0.2.0", target_version="0.3.0")


def test_pending_raises_on_duplicate_from_version():
    cms = CMS(database_url="sqlite:///dummy.db", auth="none")

    @cms.migration(from_version="0.1.0", to_version="0.2.0")
    async def m1(db):
        pass

    @cms.migration(from_version="0.1.0", to_version="0.3.0")
    async def m2(db):
        pass

    runner = MigrationRunner(cms)
    with pytest.raises(MigrationError, match="Ambiguous migration"):
        runner.pending(current_version="0.1.0", target_version="0.3.0")


# ---------------------------------------------------------------------------
# Runner — run()
# ---------------------------------------------------------------------------


async def test_run_applies_steps_and_updates_version():
    cms, db_path = _cms_with_migrations()
    try:
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            # Manually set stored version to 0.1.0
            await (
                CMSMeta.update({CMSMeta.value: "0.1.0"})
                .where(CMSMeta.key == "schema_version")
                .run()
            )

            runner = MigrationRunner(cms)
            chain = runner.pending(current_version="0.1.0", target_version="0.2.0")
            await runner.run(chain)

            rows = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
            assert rows[0]["value"] == "0.2.0"
    finally:
        os.unlink(db_path)


async def test_run_dry_run_does_not_update_version():
    cms, db_path = _cms_with_migrations()
    try:
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            await (
                CMSMeta.update({CMSMeta.value: "0.1.0"})
                .where(CMSMeta.key == "schema_version")
                .run()
            )

            runner = MigrationRunner(cms)
            chain = runner.pending(current_version="0.1.0", target_version="0.2.0")
            await runner.run(chain, dry_run=True)

            # Version must still be 0.1.0
            rows = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
            assert rows[0]["value"] == "0.1.0"
    finally:
        os.unlink(db_path)


async def test_run_calls_migration_function():
    """The migration function is actually invoked."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db_path = f.name
    called = []

    cms = CMS(database_url=f"sqlite:///{db_path}", auth="none")

    @cms.block("x")
    class X:
        title: str = TextField(required=True)

    @cms.migration(from_version="0.1.0", to_version="0.2.0")
    async def record(db):
        called.append(True)

    try:
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            await (
                CMSMeta.update({CMSMeta.value: "0.1.0"})
                .where(CMSMeta.key == "schema_version")
                .run()
            )

            runner = MigrationRunner(cms)
            chain = runner.pending(current_version="0.1.0", target_version="0.2.0")
            await runner.run(chain)

        assert called == [True]
    finally:
        os.unlink(db_path)


async def test_run_empty_chain_is_noop():
    cms, db_path = _cms_with_migrations()
    try:
        async with cms.lifespan_context(None):
            runner = MigrationRunner(cms)
            result = await runner.run([])
            assert result == []
    finally:
        os.unlink(db_path)
