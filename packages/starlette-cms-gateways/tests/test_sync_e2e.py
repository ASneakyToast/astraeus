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


# ---------------------------------------------------------------------------
# Mutability test (STORY-002)
# ---------------------------------------------------------------------------


async def test_synced_doc_is_patchable(cms_and_client):
    """Synced document can be PATCHed after creation (append_only=False default)."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [{"id": "P1", "name": "Patchable", "score": 1.0}]

    gateway = TestGateway(cms_client=client)
    await gateway.sync()

    # Find the created document
    data = await client.list_documents(doc_type="test_item")
    docs = data.get("documents", [])
    assert docs, "Expected at least one document after sync"

    doc = next(
        (d for d in docs if d.get("import_ref") == "test:item:P1"),
        None,
    )
    assert doc is not None, "Could not find synced document by import_ref"

    # Should be patchable — update it directly
    updated = await client.update_document(
        doc["id"],
        body={"name": "Patched!", "score": 99.0},
    )
    assert updated["body"]["name"] == "Patched!"


# ---------------------------------------------------------------------------
# Draft-by-default tests (STORY-003)
# ---------------------------------------------------------------------------


class DraftTestGateway(TestGateway):
    """Like TestGateway but with auto_publish=False (the new BaseGateway default)."""

    service_name = "draft_test_service"
    auto_publish = False  # explicitly False — verifies draft-by-default behaviour


async def test_sync_creates_drafts_by_default(cms_and_client):
    """Default auto_publish=False — synced docs are created as drafts (published=False)."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [{"id": "DR1", "name": "Draft Item", "score": 0.5}]

    gateway = DraftTestGateway(cms_client=client)
    result = await gateway.sync()

    assert result.created == 1
    assert not result.has_errors

    data = await client.list_documents(doc_type="test_item")
    doc = next(
        (d for d in data.get("documents", []) if d.get("import_ref") == "test:item:DR1"),
        None,
    )
    assert doc is not None, "Document should have been created"
    assert doc.get("published") is False, "Document should be a draft (published=False)"


async def test_sync_auto_publish_true_publishes_docs(cms_and_client):
    """Explicit auto_publish=True publishes docs immediately after sync."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [{"id": "PB1", "name": "Published Item", "score": 1.0}]

    # TestGateway has auto_publish=True explicitly set
    gateway = TestGateway(cms_client=client)
    result = await gateway.sync()

    assert result.created == 1
    assert not result.has_errors

    data = await client.list_documents(doc_type="test_item")
    doc = next(
        (d for d in data.get("documents", []) if d.get("import_ref") == "test:item:PB1"),
        None,
    )
    assert doc is not None, "Document should have been created"
    assert doc.get("published") is True, "Document should be published (auto_publish=True)"


# ---------------------------------------------------------------------------
# One changeset per sync run
# ---------------------------------------------------------------------------


async def _open_changesets(client) -> list[dict]:
    """List open changesets straight through the client's in-process transport."""
    http = client._get_http()
    resp = await http.get(
        "http://testserver/api/changesets", params={"status": "open"}
    )
    return resp.json()["changesets"]


async def test_sync_groups_all_writes_into_one_changeset(cms_and_client):
    """A run that writes N docs produces exactly one changeset holding all N."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [
        {"id": "G1", "name": "One", "score": 1.0},
        {"id": "G2", "name": "Two", "score": 2.0},
        {"id": "G3", "name": "Three", "score": 3.0},
    ]

    gateway = DraftTestGateway(cms_client=client)
    result = await gateway.sync()

    assert result.created == 3
    assert result.changeset_id is not None

    changesets = await _open_changesets(client)
    assert len(changesets) == 1, "The whole run should land in a single changeset"
    assert changesets[0]["id"] == result.changeset_id
    assert changesets[0]["document_count"] == 3


async def test_all_skip_run_creates_no_changeset(cms_and_client):
    """A run where every item is skipped leaves no new (empty) changeset behind."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [{"id": "S1", "name": "Same", "score": 1.0}]

    gateway = DraftTestGateway(cms_client=client)
    r1 = await gateway.sync()
    assert r1.created == 1
    assert r1.changeset_id is not None

    # Identical data → all skipped, so no changeset should be created this run.
    r2 = await gateway.sync()
    assert r2.skipped == 1
    assert r2.changeset_id is None

    changesets = await _open_changesets(client)
    assert len(changesets) == 1, "Only the first run's changeset should exist"


async def test_update_run_groups_only_written_docs(cms_and_client):
    """A later run's changeset holds only the docs it actually wrote."""
    _, client = cms_and_client
    global _FAKE_DB
    _FAKE_DB = [
        {"id": "M1", "name": "Keep", "score": 1.0},
        {"id": "M2", "name": "Before", "score": 2.0},
    ]

    gateway = DraftTestGateway(cms_client=client)
    r1 = await gateway.sync()
    assert r1.created == 2

    # Change one item; the other is untouched.
    _FAKE_DB[1] = {"id": "M2", "name": "After", "score": 22.0}
    r2 = await gateway.sync()
    assert r2.updated == 1
    assert r2.skipped == 1
    assert r2.changeset_id is not None
    assert r2.changeset_id != r1.changeset_id

    changesets = await _open_changesets(client)
    run2 = next(c for c in changesets if c["id"] == r2.changeset_id)
    assert run2["document_count"] == 1, "Only the updated doc belongs to run 2"
