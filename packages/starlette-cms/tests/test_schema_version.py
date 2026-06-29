"""
Tests that the schema-version machinery has been removed.

After the migration to Piccolo-native migrations, CMSDatabase no longer
checks or enforces a schema_version at startup — that responsibility
moved to ``piccolo migrations forwards``.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from starlette_cms import CMS, TextField


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_cms() -> tuple[CMS, str]:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    cms = CMS(database_url=f"sqlite:///{f.name}", auth="none")

    @cms.block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    return cms, f.name


# ---------------------------------------------------------------------------
# Startup succeeds regardless of what's in cms_meta.schema_version
# ---------------------------------------------------------------------------


async def test_startup_succeeds_without_version_check():
    """
    lifespan_context no longer raises on a stale or missing schema_version.
    Any value in cms_meta (or no value at all) should start cleanly.
    """
    cms, db_path = _fresh_cms()
    try:
        # First startup — fresh DB, no schema_version row
        async with cms.lifespan_context(None):
            from starlette_cms.tables import CMSMeta

            # Inject a deliberately old version
            rows = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
            if rows:
                await (
                    CMSMeta.update({CMSMeta.value: "0.0.1"})
                    .where(CMSMeta.key == "schema_version")
                    .run()
                )
            else:
                await CMSMeta.insert(CMSMeta(key="schema_version", value="0.0.1")).run()

        # Second startup with the stale version — must NOT raise
        cms2 = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @cms2.block("hero")
        class HeroBlock:
            title: str = TextField(required=True)

        async with cms2.lifespan_context(None):
            pass  # no CMSSchemaMismatch raised
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# CMSSchemaMismatch removed from public API
# ---------------------------------------------------------------------------


def test_cmsschemamismatch_removed_from_public_api():
    """
    ``from starlette_cms import CMSSchemaMismatch`` must raise ImportError —
    the class no longer exists.
    """
    with pytest.raises((ImportError, AttributeError)):
        from starlette_cms import CMSSchemaMismatch  # noqa: F401
