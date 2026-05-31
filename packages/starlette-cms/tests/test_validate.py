"""Tests for cms validate — document re-validation against current schemas."""

from __future__ import annotations

import json
import os
import tempfile

from starlette_cms import CMS, TextField
from starlette_cms.cli import _validate_documents


def _cms() -> tuple[CMS, str]:
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    cms = CMS(database_url=f"sqlite:///{f.name}", auth="none")

    @cms.block("hero")
    class HeroBlock:
        title: str = TextField(required=True)

    @cms.document("page")
    class PageDocument:
        title: str = TextField(required=True)
        slug: str = TextField(required=True)

    return cms, f.name


# ---------------------------------------------------------------------------
# All valid
# ---------------------------------------------------------------------------


async def test_validate_all_valid():
    cms, db_path = _cms()
    try:
        async with cms.lifespan_context(None):
            from nanoid import generate
            from starlette_cms.tables import CMSDocument

            await CMSDocument.insert(
                CMSDocument(
                    id=generate(size=21),
                    doc_type="page",
                    slug="home",
                    body=json.dumps({"title": "Home", "slug": "home"}),
                    meta="{}",
                    published=False,
                    published_at=None,
                )
            ).run()

        errors = await _validate_documents(cms)
        assert errors == []
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Invalid body
# ---------------------------------------------------------------------------


async def test_validate_catches_invalid_doc():
    """A document missing required fields is reported."""
    cms, db_path = _cms()
    try:
        async with cms.lifespan_context(None):
            from nanoid import generate
            from starlette_cms.tables import CMSDocument

            bad_id = generate(size=21)
            await CMSDocument.insert(
                CMSDocument(
                    id=bad_id,
                    doc_type="page",
                    slug="bad",
                    # missing required 'title' and 'slug'
                    body=json.dumps({}),
                    meta="{}",
                    published=False,
                    published_at=None,
                )
            ).run()

        errors = await _validate_documents(cms)
        assert len(errors) == 1
        doc_id, doc_type, detail = errors[0]
        assert doc_id == bad_id
        assert doc_type == "page"
        assert any("title" in d for d in detail)
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Unknown document type
# ---------------------------------------------------------------------------


async def test_validate_reports_unknown_type():
    """A document whose type is not registered gets flagged."""
    cms, db_path = _cms()
    try:
        async with cms.lifespan_context(None):
            from nanoid import generate
            from starlette_cms.tables import CMSDocument

            ghost_id = generate(size=21)
            await CMSDocument.insert(
                CMSDocument(
                    id=ghost_id,
                    doc_type="ghost_type",
                    slug="ghost",
                    body=json.dumps({"title": "x"}),
                    meta="{}",
                    published=False,
                    published_at=None,
                )
            ).run()

        errors = await _validate_documents(cms)
        assert any(doc_id == ghost_id for doc_id, _, _ in errors)
        _, _, detail = next(e for e in errors if e[0] == ghost_id)
        assert any("Unknown document type" in d for d in detail)
    finally:
        os.unlink(db_path)


# ---------------------------------------------------------------------------
# Mixed valid and invalid
# ---------------------------------------------------------------------------


async def test_validate_mixed():
    cms, db_path = _cms()
    try:
        async with cms.lifespan_context(None):
            from nanoid import generate
            from starlette_cms.tables import CMSDocument

            good_id = generate(size=21)
            bad_id = generate(size=21)

            await CMSDocument.insert(
                CMSDocument(
                    id=good_id,
                    doc_type="page",
                    slug="good",
                    body=json.dumps({"title": "Good", "slug": "good"}),
                    meta="{}",
                    published=False,
                    published_at=None,
                )
            ).run()
            await CMSDocument.insert(
                CMSDocument(
                    id=bad_id,
                    doc_type="page",
                    slug="bad",
                    body=json.dumps({"slug": "bad"}),  # missing title
                    meta="{}",
                    published=False,
                    published_at=None,
                )
            ).run()

        errors = await _validate_documents(cms)
        ids = [e[0] for e in errors]
        assert bad_id in ids
        assert good_id not in ids
    finally:
        os.unlink(db_path)
