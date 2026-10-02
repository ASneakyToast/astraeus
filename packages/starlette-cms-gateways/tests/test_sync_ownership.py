"""
Sync behaviour against a real in-process CMS: field ownership, no-op re-syncs,
auto-publish on update, deferral around human drafts, and the sync cursor.

These pin the contract a gateway's author relies on:

* a run that finds nothing new writes nothing (no PATCH, no draft, no
  ``updated_at`` churn);
* only fields the gateway *owns* are hashed and written on update, so a hand
  edit to any other field survives every later sync;
* a gateway that auto-publishes publishes each document as it is written;
* a document someone is mid-edit on is left alone and retried;
* the cursor advances after every run that did not raise.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField
from starlette_cms.fields import JSONField, NumberField
from starlette_cms_gateways.base import (
    BaseGateway,
    GatewayItem,
    SyncRange,
    SyncWindow,
)
from starlette_cms_gateways.client import CMSClient
from starlette_cms_gateways.jobstore import JobStore


class RecordingTransport(ASGITransport):
    """ASGI transport that remembers every ``(method, path)`` it carried."""

    def __init__(self, app: Any) -> None:
        super().__init__(app=app)
        self.calls: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        return await super().handle_async_request(request)

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]

    def patches(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] == "PATCH"]


# What the fake source currently holds: {"id": {"count": n, "items": [...], "noise": x}}
SOURCE: dict[str, dict[str, Any]] = {}
FETCH_BOOM: list[bool] = [False]


class OwnedGateway(BaseGateway):
    """``items``/``count`` are machine-sourced; ``title``/``notes`` belong to people."""

    service_name = "owned_service"
    block_type = "owned_doc"
    auto_publish = True
    owned_fields = ("items", "count")
    uses_window = True  # opts in to the cursor, as an incremental gateway does

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        if self.uses_window:
            await self.resolve_window()
        for key, entry in SOURCE.items():
            yield GatewayItem(
                import_ref=f"owned:{key}",
                slug=f"owned-{key}",
                title=f"Doc {key}",
                body={
                    "title": f"Doc {key}",
                    "count": float(len(entry["items"])),
                    "items": entry["items"],
                    # Volatile and not owned: changes must not cause a write.
                    "fetched_at": entry.get("noise", ""),
                },
            )
        if FETCH_BOOM[0]:
            raise RuntimeError("source went away")


class ReviewGateway(OwnedGateway):
    """Same data, but a human reviews: nothing is auto-published."""

    service_name = "review_service"
    auto_publish = False


@pytest_asyncio.fixture
async def env():
    SOURCE.clear()
    FETCH_BOOM[0] = False
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        cms = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @cms.block("owned_doc")
        class OwnedDocBlock:
            title: str = TextField(required=True)
            notes: str = TextField()
            count: float = NumberField()
            items: list | None = JSONField()
            fetched_at: str = TextField()

        app = Starlette(routes=[Mount("/", app=cms.app)])
        async with cms.lifespan_context(None):
            transport = RecordingTransport(app)
            http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
            client = CMSClient(base_url="http://testserver", _http_client=http)
            try:
                yield client, http, transport
            finally:
                await http.aclose()
    finally:
        os.unlink(db_path)


async def _doc(client: CMSClient, key: str) -> dict[str, Any]:
    doc = await client.find_by_import_ref("owned_doc", f"owned:{key}")
    assert doc is not None
    return doc


# ---------------------------------------------------------------------------
# Re-syncs write nothing
# ---------------------------------------------------------------------------


async def test_second_identical_sync_makes_no_writes(env):
    client, _, transport = env
    SOURCE.update({"a": {"items": [1, 2]}, "b": {"items": [3]}})

    gw = OwnedGateway(cms_client=client)
    first = await gw.sync()
    assert first.created == 2

    before = {k: (await _doc(client, k))["updated_at"] for k in ("a", "b")}
    transport.calls.clear()

    second = await gw.sync()

    assert (second.created, second.updated, second.skipped) == (0, 0, 2)
    assert transport.writes() == [], "a no-change run must not write anything"
    for k in ("a", "b"):
        doc = await _doc(client, k)
        assert doc["updated_at"] == before[k]
        assert doc["has_draft"] is False
        assert doc["draft_version"] == 0


async def test_change_in_a_non_owned_field_is_not_an_update(env):
    client, _, transport = env
    SOURCE["a"] = {"items": [1, 2], "noise": "t1"}
    gw = OwnedGateway(cms_client=client)
    await gw.sync()
    transport.calls.clear()

    SOURCE["a"]["noise"] = "t2"  # volatile source field, not curated
    result = await gw.sync()

    assert result.skipped == 1 and result.updated == 0
    assert transport.patches() == []
    assert (await _doc(client, "a"))["has_draft"] is False


# ---------------------------------------------------------------------------
# Updates: owned fields only, published, hand edits survive
# ---------------------------------------------------------------------------


async def test_update_publishes_and_touches_only_owned_fields(env):
    client, http, _ = env
    SOURCE["a"] = {"items": [1, 2]}
    gw = OwnedGateway(cms_client=client)
    await gw.sync()

    # A person edits the title and adds notes in the editor, then publishes.
    doc = await _doc(client, "a")
    await client.update_document(doc["id"], body={"title": "My own title", "notes": "mine"})
    await client.publish_document(doc["id"])

    SOURCE["a"]["items"] = [1, 2, 3]
    result = await gw.sync()

    assert (result.updated, result.skipped) == (1, 0)
    doc = await _doc(client, "a")
    assert doc["published"] is True
    assert doc["has_draft"] is False, "the update must be live, not parked as a draft"
    assert doc["body"]["items"] == [1, 2, 3]
    assert doc["body"]["count"] == 3
    assert doc["body"]["title"] == "My own title"
    assert doc["body"]["notes"] == "mine"


async def test_hand_edit_survives_a_sync_with_nothing_new(env):
    client, _, transport = env
    SOURCE["a"] = {"items": [1]}
    gw = OwnedGateway(cms_client=client)
    await gw.sync()
    doc = await _doc(client, "a")
    await client.update_document(doc["id"], body={"title": "Edited"})
    await client.publish_document(doc["id"])
    transport.calls.clear()

    await gw.sync()

    assert (await _doc(client, "a"))["body"]["title"] == "Edited"
    assert transport.writes() == []


async def test_publishing_one_at_a_time_leaves_no_open_changesets(env):
    """Each document is published as soon as it is written, and no changeset is opened.

    The CMS links every PATCH into a date-titled changeset unless told not to; with
    one publish per document that would leave one open changeset per updated doc.
    """
    client, http, transport = env
    SOURCE.update({"a": {"items": [1]}, "b": {"items": [1]}})
    gw = OwnedGateway(cms_client=client)
    created = await gw.sync()
    assert created.changeset_id is None

    SOURCE["a"]["items"] = [1, 2]
    SOURCE["b"]["items"] = [1, 2]
    transport.calls.clear()
    updated = await gw.sync()
    assert updated.updated == 2 and updated.changeset_id is None

    # Each PATCH is followed by that document's own publish; no batch publish.
    paths = [p for m, p in transport.writes()]
    assert not any(p.startswith("/api/changesets") for p in paths)
    assert sum(1 for p in paths if p.endswith("/publish")) == 2
    resp = await http.get("/api/changesets", params={"status": "open"})
    assert resp.json()["changesets"] == [], "must not leave open changesets"
    for k in ("a", "b"):
        assert (await _doc(client, k))["body"]["items"] == [1, 2]
        assert (await _doc(client, k))["has_draft"] is False


async def test_review_gateway_still_leaves_drafts_for_review(env):
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    gw = ReviewGateway(cms_client=client)
    await gw.sync()
    doc = await client.find_by_import_ref("owned_doc", "owned:a")
    assert doc["published"] is False


class MixedGateway(OwnedGateway):
    """Per-item overrides of the gateway's publish default."""

    service_name = "mixed_service"
    auto_publish = True

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        async for item in super().fetch():
            item.published = item.import_ref != "owned:held"
            yield item


class MixedReviewGateway(OwnedGateway):
    service_name = "mixed_review_service"
    auto_publish = False

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        async for item in super().fetch():
            item.published = item.import_ref == "owned:go"
            yield item


async def test_item_can_opt_out_of_an_auto_publishing_gateway(env):
    client, _, _ = env
    SOURCE.update({"live": {"items": [1]}, "held": {"items": [2]}})
    gw = MixedGateway(cms_client=client)
    await gw.sync()
    assert (await _doc(client, "live"))["published"] is True
    assert (await _doc(client, "held"))["published"] is False

    SOURCE["live"]["items"] = [1, 9]
    SOURCE["held"]["items"] = [2, 9]
    await gw.sync()
    assert (await _doc(client, "live"))["body"]["items"] == [1, 9]
    held = await _doc(client, "held")
    assert held["published"] is False, "the opted-out item must not ride the batch publish"


async def test_item_can_opt_in_on_a_review_gateway(env):
    client, _, _ = env
    SOURCE.update({"go": {"items": [1]}, "wait": {"items": [2]}})
    gw = MixedReviewGateway(cms_client=client)
    await gw.sync()
    assert (await _doc(client, "go"))["published"] is True
    assert (await _doc(client, "wait"))["published"] is False

    SOURCE["go"]["items"] = [1, 9]
    await gw.sync()
    go = await _doc(client, "go")
    assert go["body"]["items"] == [1, 9] and go["has_draft"] is False


# ---------------------------------------------------------------------------
# Deferral
# ---------------------------------------------------------------------------


async def test_pending_human_draft_is_deferred_not_overwritten(env):
    client, _, transport = env
    SOURCE["a"] = {"items": [1]}
    gw = OwnedGateway(cms_client=client)
    await gw.sync()

    doc = await _doc(client, "a")
    await client.update_document(doc["id"], body={"notes": "half-written"})  # unpublished draft
    transport.calls.clear()

    SOURCE["a"]["items"] = [1, 2]
    result = await gw.sync()

    assert result.deferred == ["owned:a"]
    assert result.updated == 0
    assert transport.writes() == []
    doc = await _doc(client, "a")
    assert doc["body"]["items"] == [1], "live content untouched"

    # Once the person publishes, the next sync catches the doc up.
    await client.publish_document(doc["id"])
    result = await gw.sync()
    assert result.updated == 1
    assert (await _doc(client, "a"))["body"]["items"] == [1, 2]


async def test_document_a_human_unpublished_is_deferred(env):
    client, http, _ = env
    SOURCE["a"] = {"items": [1]}
    gw = OwnedGateway(cms_client=client)
    await gw.sync()
    doc = await _doc(client, "a")
    resp = await http.post(f"/api/documents/{doc['id']}/unpublish")
    assert resp.status_code == 200

    SOURCE["a"]["items"] = [1, 2]
    result = await gw.sync()

    assert result.deferred == ["owned:a"]
    assert (await _doc(client, "a"))["published"] is False


# ---------------------------------------------------------------------------
# Range and cursor
# ---------------------------------------------------------------------------


def test_sync_range_validation():
    assert SyncRange.parse().mode == "since_last_sync"
    assert SyncRange.parse(default="all_time").mode == "all_time"
    assert SyncRange.parse(start="2026-01-01").mode == "custom"
    assert SyncRange.parse("custom", "2026-01-01", "2026-02-01").end == date(2026, 2, 1)
    with pytest.raises(ValueError):
        SyncRange.parse("custom")  # no dates
    with pytest.raises(ValueError):
        SyncRange.parse("all_time", "2026-01-01")  # dates need custom
    with pytest.raises(ValueError):
        SyncRange.parse("custom", "2026-03-01", "2026-02-01")  # backwards
    with pytest.raises(ValueError):
        SyncRange.parse("sometimes")


def test_window_resolution():
    overlap = timedelta(days=1)
    cursor = datetime(2026, 9, 10, 12, tzinfo=UTC)

    w = SyncWindow.resolve(SyncRange("since_last_sync"), None, overlap)
    assert (w.mode, w.changed_since, w.fell_back) == ("all_time", None, True)

    w = SyncWindow.resolve(SyncRange("since_last_sync"), cursor, overlap)
    assert (w.mode, w.changed_since) == ("since_last_sync", cursor - overlap)

    w = SyncWindow.resolve(SyncRange("all_time"), cursor, overlap)
    assert (w.mode, w.changed_since) == ("all_time", None)

    jan, feb = date(2026, 1, 1), date(2026, 2, 1)
    w = SyncWindow.resolve(SyncRange("custom", jan, feb), cursor, overlap)
    assert (w.mode, w.start, w.end, w.changed_since) == ("custom", jan, feb, None)


async def test_cursor_advances_after_clean_run_and_sets_the_next_window(env, tmp_path):
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")
    gw = OwnedGateway(cms_client=client, job_store=store)

    assert await store.get_cursor("owned_service") is None
    r1 = await gw.sync()
    assert r1.window.mode == "all_time" and r1.window.fell_back
    cursor = await store.get_cursor("owned_service")
    assert cursor == r1.started_at

    r2 = await gw.sync()
    assert r2.window.mode == "since_last_sync"
    assert r2.window.changed_since == cursor - OwnedGateway.cursor_overlap


async def test_all_time_override_ignores_the_cursor_and_still_advances_it(env, tmp_path):
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")
    gw = OwnedGateway(cms_client=client, job_store=store)
    await gw.sync()
    old = await store.get_cursor("owned_service")

    r = await gw.sync(SyncRange("all_time"))

    assert r.window.mode == "all_time" and not r.window.fell_back
    assert await store.get_cursor("owned_service") > old


async def test_custom_range_does_not_move_the_cursor(env, tmp_path):
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")
    gw = OwnedGateway(cms_client=client, job_store=store)

    r = await gw.sync(SyncRange.parse("custom", "2026-01-01", "2026-01-31"))

    assert gw.range.mode == "custom"
    assert (r.window.start, r.window.end) == (date(2026, 1, 1), date(2026, 1, 31))
    assert await store.get_cursor("owned_service") is None


async def test_failed_run_does_not_advance_the_cursor(env, tmp_path):
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")
    gw = OwnedGateway(cms_client=client, job_store=store)
    await gw.sync()
    good = await store.get_cursor("owned_service")

    SOURCE["a"]["items"] = [1, 2]
    FETCH_BOOM[0] = True
    with pytest.raises(RuntimeError):
        await gw.sync()

    assert await store.get_cursor("owned_service") == good
    # The item fetched before the failure was still written and published.
    assert (await _doc(client, "a"))["body"]["items"] == [1, 2]
    assert (await _doc(client, "a"))["has_draft"] is False


async def test_gateway_that_never_resolves_a_window_gets_no_cursor(env, tmp_path):
    """ADR 015: the framework prescribes no cursor; only opted-in gateways get one."""
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")

    class Plain(OwnedGateway):
        uses_window = False

    r = await Plain(cms_client=client, job_store=store).sync()

    assert r.window is None
    assert await store.get_cursor("owned_service") is None


async def test_cursor_advances_after_a_run_that_deferred_or_errored(env, tmp_path):
    """Deferred and failed items are reported; they never hold the cursor back."""
    client, _, _ = env
    SOURCE["a"] = {"items": [1]}
    store = JobStore(tmp_path / "jobs.db")
    gw = OwnedGateway(cms_client=client, job_store=store)
    await gw.sync()
    before = await store.get_cursor("owned_service")

    doc = await _doc(client, "a")
    await client.update_document(doc["id"], body={"notes": "wip"})
    SOURCE["a"]["items"] = [1, 2]
    r = await gw.sync()

    assert r.deferred == ["owned:a"]
    assert await store.get_cursor("owned_service") == r.started_at > before

    # A body the CMS rejects is an item error, not a crash, and the cursor moves too.
    SOURCE["a"]["items"] = "not-a-list"
    await client.discard_draft(doc["id"])
    r = await gw.sync()
    assert r.has_errors
    assert await store.get_cursor("owned_service") == r.started_at
