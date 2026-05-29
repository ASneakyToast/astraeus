"""
Shared test fixtures for starlette-cms.

Provides:
- ``cms_factory`` — function-scoped factory that creates a fresh CMS with a
  temp SQLite file (piccolo opens a new connection per query, so :memory:
  doesn't share state across async calls without shared-cache, and shared-
  cache has aiosqlite limitations in some pytest-asyncio modes).
- ``cms`` — a pre-built CMS with HeroBlock + PageDocument registered.
- ``client`` — an ``httpx.AsyncClient`` wired to the cms.app via ASGITransport.

Usage::

    async def test_something(client):
        resp = await client.get("/api/schema")
        assert resp.status_code == 200
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncGenerator

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, RichTextField, TextField
from starlette_cms.fields import BlockField


@pytest_asyncio.fixture
async def cms() -> AsyncGenerator[CMS, None]:
    """
    CMS instance with HeroBlock and PageDocument registered, running against
    a temporary SQLite file.

    Startup/shutdown lifecycle is run so the DB tables exist.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

        @instance.block("hero")
        class HeroBlock:
            title: str = TextField(required=True, label="Headline")
            subtitle: str = TextField(required=False, label="Subtitle")
            body: dict = RichTextField()

        @instance.document("page")
        class PageDocument:
            title: str = TextField(required=True)
            slug: str = TextField(required=True)
            hero: dict = BlockField(required=False)

        # Run the lifespan startup
        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def client(cms: CMS) -> AsyncGenerator[httpx.AsyncClient, None]:
    """httpx.AsyncClient targeting cms.app via ASGITransport."""
    app = Starlette(routes=[Mount("/", app=cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def authed_cms() -> AsyncGenerator[CMS, None]:
    """CMS instance with apikey auth for auth tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="apikey",
            api_key="test-secret",
            read_auth=False,
        )

        @instance.block("hero")
        class HeroBlock:
            title: str = TextField(required=True)

        @instance.document("page")
        class PageDocument:
            title: str = TextField(required=True)
            slug: str = TextField(required=True)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def authed_client(authed_cms: CMS) -> AsyncGenerator[httpx.AsyncClient, None]:
    """httpx.AsyncClient for the apikey-protected CMS."""
    app = Starlette(routes=[Mount("/", app=authed_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c
