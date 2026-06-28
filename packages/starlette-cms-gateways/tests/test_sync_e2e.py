"""
End-to-end sync tests: a real starlette-cms instance + a test gateway.

Tests:
1. First sync creates all items.
2. Second sync (no changes) skips all — idempotency.
3. Third sync with a changed item updates only that item.

The CMS is spun up using httpx.AsyncClient with ASGITransport so no network
port is opened.  CMSClient is patched to use the same in-process ASGI client
so all HTTP calls go through the CMS's routes.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField
from starlette_cms.fields import NumberField

from starlette_cms_gateways.base import BaseGateway, GatewayItem
from starlette_cms_gateways.client import CMSClient


# ---------------------------------------------------------------------------
# Test gateway implementation
# ---------------------------------------------------------------------------

# Shared "database" that the test gateway reads from — mutated per test
_FAKE_DB: list[dict] = []


class TestGateway(BaseGateway):
    """Minimal gateway that yields items from the module-level _FAKE_DB."""

    service_name = "test_service"
    block_type = "test_item"
    auto_publish = True

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        for entry in _FAKE_DB:
            yield GatewayItem(
                import_ref=f"test:item:{entry['id']}",
                slug=f"test-item-{entry['id']}",
                body={"name": entry["name"], "score": entry["score"]},
            )


# ---------------------------------------------------------------------------
# Fixture: in-process CMS + CMSClient
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def cms_and_client():
    """
    Spin up a real CMS with in-process ASGI transport.  Returns (cms, client)
    where client is a CMSClient whose underlying httpx client uses ASGITransport.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.block("test_item")
        class TestItemBlock:
            name: str = TextField(required=True)
            score: float = NumberField()

        starlette_app = Starlette(routes=[Mount("/", app=instance.app)])

        async with instance.lifespan_context(None):
            # Build an httpx client that routes through the ASGI app
            transport = ASGITransport(app=starlette_app)
            http = httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            )
            cms_client = CMSClient(
                base_url="http://testserver",
                api_key=None,
                _http_client=http,
            )
            try:
                yield instance, cms_client
            finally:
                await http.aclose()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_first_sync_creates_all_items(cms_and_client):
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [
        {"id": "1", "name": "Alpha", "score": 1.0},
        {"id": "2", "name": "Beta", "score": 2.0},
        {"id": "3", "name": "Gamma", "score": 3.0},
    ]

    gateway = TestGateway(cms_client=client)
    result = await gateway.sync()

    assert result.created == 3
    assert result.updated == 0
    assert result.skipped == 0
    assert not result.has_errors


async def test_second_sync_skips_all_identical(cms_and_client):
    """Second sync run with identical data → all skipped."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [
        {"id": "A1", "name": "ItemA", "score": 10.0},
        {"id": "A2", "name": "ItemB", "score": 20.0},
    ]

    gateway = TestGateway(cms_client=client)

    # First sync: create both
    r1 = await gateway.sync()
    assert r1.created == 2

    # Second sync: same data → both skipped
    r2 = await gateway.sync()
    assert r2.created == 0
    assert r2.updated == 0
    assert r2.skipped == 2


async def test_third_sync_updates_changed_item(cms_and_client):
    """If one item's body changes, it should be updated; unchanged items skipped."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [
        {"id": "U1", "name": "Unchanged", "score": 5.0},
        {"id": "U2", "name": "Will Change", "score": 5.0},
    ]

    gateway = TestGateway(cms_client=client)
    r1 = await gateway.sync()
    assert r1.created == 2

    # Mutate one item
    _FAKE_DB[1] = {"id": "U2", "name": "Changed!", "score": 99.0}

    r2 = await gateway.sync()
    assert r2.created == 0
    assert r2.updated == 1
    assert r2.skipped == 1


async def test_sync_result_has_no_errors_on_clean_run(cms_and_client):
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [{"id": "E1", "name": "ErrorFree", "score": 0.0}]

    gateway = TestGateway(cms_client=client)
    result = await gateway.sync()
    assert not result.has_errors
    assert result.finished_at is not None
