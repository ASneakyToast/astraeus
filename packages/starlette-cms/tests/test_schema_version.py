"""Tests for the startup schema version check."""

from __future__ import annotations

import os
import tempfile

import pytest
from starlette_cms import CMS, TextField
from starlette_cms.exceptions import CMSSchemaMismatch


def _fresh_cms(version_override: str | None = None) -> tuple[CMS, str]:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    cms = CMS(database_url=f"sqlite:///{f.name}", auth="none")

    @cms.block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    return cms, f.name


# ---------------------------------------------------------------------------
# Fresh database — no mismatch
# ---------------------------------------------------------------------------


async def test_fresh_db_seeds_version_and_starts():
    """A brand-new DB has no schema_version; init() seeds it and does not raise."""
    cms, db_path = _fresh_cms()
    try:
        async with cms.lifespan_context(None):
            from starlette_cms import __version__
            from starlette_cms.tables import CMSMeta

            rows = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
            assert rows, "schema_version row should have been seeded"
            assert rows[0]["value"] == __version__
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Matching version — no mismatch
# ---------------------------------------------------------------------------


async def test_matching_version_starts_cleanly():
    """A DB whose schema_version matches the package version starts without error."""
    cms, db_path = _fresh_cms()
    try:
        # First startup seeds the version
        async with cms.lifespan_context(None):
            pass

        # Second startup should see the correct version and not raise
        cms2 = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @cms2.block("hero")
        class HeroBlock:
            title: str = TextField(required=True)

        async with cms2.lifespan_context(None):
            pass  # should not raise
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Mismatching version — raises CMSSchemaMismatch
# ---------------------------------------------------------------------------


async def test_version_mismatch_raises():
    """A DB whose stored version differs from the package version raises CMSSchemaMismatch."""
    cms, db_path = _fresh_cms()
    try:
        # Seed the DB with a deliberately old version
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            await (
                CMSMeta.update({CMSMeta.value: "0.0.1"})
                .where(CMSMeta.key == "schema_version")
                .run()
            )

        # Next startup should refuse
        cms2 = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @cms2.block("hero")
        class HeroBlock:
            title: str = TextField(required=True)

        with pytest.raises(CMSSchemaMismatch, match="0.0.1"):
            async with cms2.lifespan_context(None):
                pass
    finally:
        os.unlink(db_path)


async def test_mismatch_error_mentions_migrate():
    """The error message directs the user to run `cms migrate`."""
    cms, db_path = _fresh_cms()
    try:
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            await (
                CMSMeta.update({CMSMeta.value: "0.0.1"})
                .where(CMSMeta.key == "schema_version")
                .run()
            )

        cms2 = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @cms2.block("hero")
        class HeroBlock:
            title: str = TextField(required=True)

        with pytest.raises(CMSSchemaMismatch, match="cms migrate"):
            async with cms2.lifespan_context(None):
                pass
    finally:
        os.unlink(db_path)
