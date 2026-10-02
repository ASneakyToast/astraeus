"""
Sync state against a real in-process CMS: the cursor, the retry list, drafts, and
publishing one document at a time.

What these pin (ADR 018):

* the cursor lives in the CMS's database and is one value, seen identically by the
  admin API, a worker over the gateway API (MCP, CLI) and a restarted CMS;
* a run that did not raise moves the cursor to its start, whatever it deferred or
  failed on; those documents go on the retry list and are tried again next run;
* a gateway's own leftover draft (a publish that failed, a revision awaiting review)
  is finished or updated; a person's draft is never touched;
* each document is published as soon as it is written, and no changeset is left open.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField
from starlette_cms.fields import JSONField, NumberField
from starlette_cms_gateways.admin import GatewayAdmin
from starlette_cms_gateways.base import BaseGateway, GatewayItem, SyncRange
from starlette_cms_gateways.cli import run_sync_via_cms
from starlette_cms_gateways.client import CMSClient
from starlette_cms_gateways.drafts import draft_verdict
from starlette_cms_gateways.runner import run_recorded
from starlette_cms_gateways.state import RemoteSyncState, RetryEntry

pytestmark = pytest.mark.asyncio

API_KEY = "k"

# What the fake source holds, and what "changed at the source" since the last run.
SOURCE: dict[str, list[int]] = {}
CHANGED: list[set[str] | None] = [None]  # None: everything is yielded
REFETCHED: list[list[str]] = []


def _item(key: str) -> GatewayItem:
    items = SOURCE[key]
    return GatewayItem(
        import_ref=f"owned:{key}",
        slug=f"owned-{key}",
        title=f"Doc {key}",
        body={"title": f"Doc {key}", "items": items, "count": float(len(items))},
    )


class StateGateway(BaseGateway):
    """Incremental: fetch yields only what changed; refetch rebuilds named refs."""

    service_name = "state_service"
    block_type = "owned_doc"
    auto_publish = True
    owned_fields = ("items", "count")

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        await self.resolve_window()
        for key in SOURCE if CHANGED[0] is None else sorted(CHANGED[0]):
            yield _item(key)

    async def refetch(self, import_refs):  # type: ignore[no-untyped-def]
        REFETCHED.append(list(import_refs))
        for ref in import_refs:
            key = ref.removeprefix("owned:")
            if key in SOURCE:
                yield _item(key)


class NoHookGateway(StateGateway):
    """Same, without the optional hook: it can only report its retry list."""

    service_name = "nohook_service"
    refetch = BaseGateway.refetch


class ReviewGateway(StateGateway):
    service_name = "review_service"
    auto_publish = False


class UndeclaredGateway(StateGateway):
    """No ``owned_fields``: it cannot tell its own draft from a person's."""

    service_name = "undeclared_service"
    owned_fields = None


GATEWAYS = {
    "state-gw": StateGateway,
    "nohook-gw": NoHookGateway,
    "review-gw": ReviewGateway,
    "undeclared-gw": UndeclaredGateway,
}


class FlakyTransport(ASGITransport):
    """Fails the next *n* publish calls with a 500, as a flaky network would."""

    def __init__(self, app: Any) -> None:
        super().__init__(app=app)
        self.fail_publishes = 0
        self.calls: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if (
            request.method == "POST"
            and request.url.path.endswith("/publish")
            and self.fail_publishes
        ):
            self.fail_publishes -= 1
            return httpx.Response(500, text="publish failed")
        return await super().handle_async_request(request)

    def writes(self) -> list[tuple[str, str]]:
        return [c for c in self.calls if c[0] != "GET"]


class Stack:
    def __init__(self, cms: CMS, admin: GatewayAdmin, http: httpx.AsyncClient, transport):
        self.cms, self.admin, self.http, self.transport = cms, admin, http, transport
        self.client = CMSClient(base_url="http://testserver", api_key=API_KEY, _http_client=http)

    async def doc(self, key: str) -> dict[str, Any]:
        doc = await self.client.find_by_import_ref("owned_doc", f"owned:{key}")
        assert doc is not None
        return doc

    def gateway(self, name: str, state: Any = None) -> BaseGateway:
        return GATEWAYS[name](
            cms_client=self.client, job_store=state or self.admin.jobs, job_store_key=name
        )

    async def human_edit(self, key: str, **body: Any) -> None:
        """A person edits in the editor: an unpublished draft."""
        doc = await self.doc(key)
        await self.client.update_document(doc["id"], body=body)

    async def human_publish(self, key: str) -> None:
        await self.client.publish_document((await self.doc(key))["id"])

    async def open_changesets(self) -> list[dict]:
        resp = await self.http.get(
            "/api/changesets",
            params={"status": "open"},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        return resp.json()["changesets"]


@asynccontextmanager
async def running(db_path: Path):
    """A CMS + GatewayAdmin on *db_path*. Call again on the same path to 'restart'."""
    cms = CMS(database_url=f"sqlite:///{db_path}", auth="apikey", api_key=API_KEY)

    @cms.block("owned_doc")
    class OwnedDocBlock:
        title: str = TextField(required=True)
        notes: str = TextField()
        count: float = NumberField()
        items: list | None = JSONField()

    admin = GatewayAdmin(cms=cms)  # default: the CMS's own database file
    app = Starlette(routes=[Mount("/", app=cms.app)])
    async with cms.lifespan_context(None):
        transport = FlakyTransport(app)
        http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        try:
            yield Stack(cms, admin, http, transport)
        finally:
            await http.aclose()


@pytest.fixture(autouse=True)
def _reset():
    SOURCE.clear()
    CHANGED[0] = None
    REFETCHED.clear()
    with patch("starlette_cms_gateways.admin.api.discover_gateways", return_value=GATEWAYS):
        yield


@pytest.fixture
async def stack(tmp_path):
    async with running(tmp_path / "content.db") as s:
        yield s


# ---------------------------------------------------------------------------
# The cursor: one value, in the CMS's database
# ---------------------------------------------------------------------------


async def test_default_state_file_is_the_cms_database(tmp_path):
    async with running(tmp_path / "content.db") as s:
        assert Path(s.admin.jobs.path) == tmp_path / "content.db"


async def test_cursor_is_one_value_across_admin_api_worker_and_restart(tmp_path):
    db = tmp_path / "content.db"
    SOURCE["a"] = [1]
    auth = {"Authorization": f"Bearer {API_KEY}"}

    async with running(db) as s:
        # 1. A run from the admin page.
        resp = await s.http.post("/api/gateways/state-gw/sync", headers=auth)
        assert resp.status_code == 202
        run_id = resp.json()["run_id"]
        for _ in range(100):
            job = (await s.http.get(f"/api/gateways/state-gw/sync/{run_id}")).json()
            if job["status"] != "running":
                break
            await asyncio.sleep(0.05)
        assert job["status"] == "done"
        admin_cursor = (await s.http.get("/api/gateways/state-gw/cursor", headers=auth)).json()[
            "cursor"
        ]
        assert admin_cursor

        # 2. A worker outside the CMS (the MCP sidecar) reads the very same value...
        remote = RemoteSyncState(s.client)
        assert await remote.get_cursor("state-gw") == datetime.fromisoformat(admin_cursor)

        # ...and moves it with a run of its own.
        mcp_result = await run_recorded(s.gateway("state-gw", remote), remote, "state-gw")
        assert mcp_result.window.mode == "since_last_sync", "it saw the admin run's cursor"
        mcp_cursor = (await s.http.get("/api/gateways/state-gw/cursor", headers=auth)).json()[
            "cursor"
        ]
        assert datetime.fromisoformat(mcp_cursor) == mcp_result.started_at
        assert mcp_cursor > admin_cursor

        # 3. So does the CLI's code path, and the admin listing agrees.
        cli_result = await run_sync_via_cms(StateGateway, "state-gw", s.client, None)
        listing = (await s.http.get("/api/gateways", headers=auth)).json()["gateways"]
        listed = next(g for g in listing if g["name"] == "state-gw")
        assert datetime.fromisoformat(listed["cursor"]) == cli_result.started_at
        assert await s.admin.jobs.get_cursor("state-gw") == cli_result.started_at
        final = listed["cursor"]

        # Runs from all three show in the job history, so "last synced" is true.
        jobs = await s.admin.jobs.list_for_gateway("state-gw")
        assert len(jobs) == 3 and all(j["status"] == "done" for j in jobs)
        assert await s.admin.jobs.get_last_synced("state-gw") is not None

    # 4. Restart: a new CMS and admin on the same file.
    async with running(db) as s2:
        got = (await s2.http.get("/api/gateways/state-gw/cursor", headers=auth)).json()["cursor"]
        assert got == final
        assert await RemoteSyncState(s2.client).get_cursor("state-gw") == datetime.fromisoformat(
            final
        )


async def test_retry_list_survives_a_restart(tmp_path):
    db = tmp_path / "content.db"
    SOURCE["a"] = [1]
    async with running(db) as s:
        await s.admin.jobs.set_retry(
            "state-gw", [RetryEntry("owned:a", "deferred", "", "2026-10-01T00:00:00+00:00")]
        )
    async with running(db) as s2:
        entries = await RemoteSyncState(s2.client).get_retry("state-gw")
        assert [(e.import_ref, e.reason, e.since) for e in entries] == [
            ("owned:a", "deferred", "2026-10-01T00:00:00+00:00")
        ]


async def test_state_routes_need_auth_and_a_known_gateway(stack):
    s = stack
    anon = httpx.AsyncClient(transport=s.transport, base_url="http://testserver")
    for method, path in [
        ("GET", "/api/gateways/state-gw/cursor"),
        ("PUT", "/api/gateways/state-gw/cursor"),
        ("GET", "/api/gateways/state-gw/retry"),
        ("POST", "/api/gateways/state-gw/runs"),
    ]:
        resp = await anon.request(method, path, json={})
        assert resp.status_code in (401, 403), (method, path, resp.status_code)
    await anon.aclose()

    auth = {"Authorization": f"Bearer {API_KEY}"}
    assert (await s.http.get("/api/gateways/nope/cursor", headers=auth)).status_code == 404
    bad = await s.http.put(
        "/api/gateways/state-gw/cursor", json={"cursor": "yesterday"}, headers=auth
    )
    assert bad.status_code == 422
    bad = await s.http.put(
        "/api/gateways/state-gw/retry", json={"entries": [{"nope": 1}]}, headers=auth
    )
    assert bad.status_code == 422


async def test_cursor_advances_after_a_run_that_deferred_or_errored(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    first = await gw.sync()
    await s.human_edit("a", notes="wip")
    SOURCE["a"] = [1, 2]
    second = await gw.sync()
    assert second.deferred == ["owned:a"]
    assert await s.admin.jobs.get_cursor("state-gw") == second.started_at > first.started_at
    assert [e.import_ref for e in await s.admin.jobs.get_retry("state-gw")] == ["owned:a"]


# ---------------------------------------------------------------------------
# A publish that fails mid-run
# ---------------------------------------------------------------------------


async def test_failed_publish_after_update_is_finished_next_run(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()

    SOURCE["a"] = [1, 2]
    s.transport.fail_publishes = 1
    broken = await gw.sync()
    assert broken.has_errors and broken.updated == 0
    stuck = await s.doc("a")
    assert stuck["has_draft"] is True and stuck["body"]["items"] == [1], "PATCHed, not live"
    assert [(e.import_ref, e.reason) for e in await s.admin.jobs.get_retry("state-gw")] == [
        ("owned:a", "error")
    ]

    # Nothing changed at the source; the hash already matches the draft's. It must
    # still be re-PATCHed and published: not skipped, and not deferred as 'a draft'.
    CHANGED[0] = set()
    fixed = await gw.sync()

    assert (fixed.updated, fixed.skipped, fixed.deferred, fixed.errors) == (1, 0, [], [])
    assert fixed.recovered == ["owned:a"]
    done = await s.doc("a")
    assert done["has_draft"] is False and done["published"] is True
    assert done["body"]["items"] == [1, 2]
    assert await s.admin.jobs.get_retry("state-gw") == []


async def test_failed_publish_after_create_is_published_next_run(stack):
    s = stack
    SOURCE["a"] = [1]
    s.transport.fail_publishes = 1
    gw = s.gateway("state-gw")
    first = await gw.sync()
    assert first.has_errors
    assert (await s.doc("a"))["published"] is False

    CHANGED[0] = set()
    second = await gw.sync()

    assert (second.updated, second.skipped, second.deferred) == (1, 0, [])
    assert (await s.doc("a"))["published"] is True


# ---------------------------------------------------------------------------
# The review workflow
# ---------------------------------------------------------------------------


async def test_review_gateway_takes_a_second_and_third_update_to_a_never_published_draft(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("review-gw")
    created = await gw.sync()
    assert created.created == 1

    for items in ([1, 2], [1, 2, 3], [1, 2, 3, 4]):
        SOURCE["a"] = items
        r = await gw.sync()
        assert (r.updated, r.deferred, r.errors) == (1, [], []), items
        doc = await s.doc("a")
        assert doc["published"] is False and doc["has_draft"] is True
        draft = await s.client.get_draft_body(doc["id"])
        assert draft["items"] == items

    # Unchanged source: the pending draft already says it, so nothing is written.
    s.transport.calls.clear()
    r = await gw.sync()
    assert (r.skipped, r.updated) == (1, 0) and s.transport.writes() == []


async def test_review_gateway_defers_when_a_reviewer_edits_the_draft(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("review-gw")
    await gw.sync()
    SOURCE["a"] = [1, 2]
    await gw.sync()
    await s.human_edit("a", notes="reviewer's note")  # touches a non-owned field

    SOURCE["a"] = [1, 2, 3]
    r = await gw.sync()

    assert r.deferred == ["owned:a"]
    draft = await s.client.get_draft_body((await s.doc("a"))["id"])
    assert draft["items"] == [1, 2] and draft["notes"] == "reviewer's note"


async def test_gateway_without_owned_fields_defers_on_any_draft(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("undeclared-gw")
    await gw.sync()
    SOURCE["a"] = [1, 2]
    s.transport.fail_publishes = 1
    await gw.sync()  # leaves its own draft behind
    SOURCE["a"] = [1, 2, 3]
    r = await gw.sync()
    assert r.deferred == ["owned:a"], "without owned_fields it cannot tell whose draft that is"


# ---------------------------------------------------------------------------
# A person's draft: deferred, listed, retried once they publish
# ---------------------------------------------------------------------------


async def test_human_draft_is_deferred_listed_and_retried_after_they_publish(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()

    await s.human_edit("a", notes="half-written")
    SOURCE["a"] = [1, 2]
    CHANGED[0] = {"a"}
    r = await gw.sync()
    assert r.deferred == ["owned:a"]
    assert [(e.import_ref, e.reason) for e in r.retry] == [("owned:a", "deferred")]
    since = r.retry[0].since
    assert (await s.doc("a"))["body"]["items"] == [1], "live content untouched"

    # Still not published: still deferred, and it keeps the time it first went on the list.
    CHANGED[0] = set()
    r = await gw.sync()
    assert REFETCHED[-1] == ["owned:a"], "asked the gateway to re-fetch it"
    assert r.deferred == ["owned:a"] and r.retry[0].since == since

    await s.human_publish("a")
    r = await gw.sync()

    assert (r.updated, r.deferred, r.errors) == (1, [], [])
    assert r.recovered == ["owned:a"] and r.retry == []
    doc = await s.doc("a")
    assert doc["body"]["items"] == [1, 2] and doc["body"]["notes"] == "half-written"
    assert await s.admin.jobs.get_retry("state-gw") == []


async def test_a_person_draft_with_nothing_new_at_the_source_is_not_a_deferral(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()
    await s.human_edit("a", notes="wip")

    r = await gw.sync()  # source unchanged: nothing for the gateway to write or wait for

    assert (r.skipped, r.deferred) == (1, [])
    assert await s.admin.jobs.get_retry("state-gw") == []


async def test_a_staged_unpublish_is_not_the_gateways_draft(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()
    doc = await s.doc("a")
    resp = await s.http.post(
        f"/api/documents/{doc['id']}/draft-publish-state",
        json={"published": False},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    assert resp.status_code == 200, resp.text
    SOURCE["a"] = [1, 2]
    r = await gw.sync()
    assert r.deferred == ["owned:a"]


async def test_gateway_without_a_refetch_hook_only_reports(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("nohook-gw")
    await gw.sync()
    await s.human_edit("a", notes="wip")
    SOURCE["a"] = [1, 2]
    CHANGED[0] = {"a"}
    await gw.sync()

    CHANGED[0] = set()
    r = await gw.sync()

    assert REFETCHED == [], "no hook, nothing to call"
    assert [e.import_ref for e in r.retry] == ["owned:a"], "it stays on the list"
    assert r.dropped == [] and r.deferred == []


async def test_a_ref_the_source_no_longer_has_is_dropped_from_the_retry_list(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()
    await s.human_edit("a", notes="wip")
    SOURCE["a"] = [1, 2]
    CHANGED[0] = {"a"}
    await gw.sync()

    del SOURCE["a"]  # gone upstream
    CHANGED[0] = set()
    r = await gw.sync()

    assert r.dropped == ["owned:a"] and r.retry == []
    assert await s.admin.jobs.get_retry("state-gw") == []


async def test_retry_refs_are_processed_once_even_if_fetch_yields_them_too(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()
    await s.human_edit("a", notes="wip")
    SOURCE["a"] = [1, 2]
    await gw.sync()

    await s.human_publish("a")
    s.transport.calls.clear()
    SOURCE["a"] = [1, 2, 3]
    r = await gw.sync()  # CHANGED is None: fetch yields 'a' as well as refetch

    assert r.updated == 1
    assert sum(1 for m, p in s.transport.writes() if m == "PATCH") == 1


# ---------------------------------------------------------------------------
# Publishing one at a time
# ---------------------------------------------------------------------------


async def test_updates_leave_no_open_changesets(stack):
    s = stack
    SOURCE.update({"a": [1], "b": [1], "c": [1]})
    gw = s.gateway("state-gw")
    await gw.sync()
    for k in SOURCE:
        SOURCE[k] = [1, 2]
    r = await gw.sync()
    assert r.updated == 3 and r.changeset_id is None
    assert await s.open_changesets() == []


async def test_one_failed_publish_strands_one_document_not_the_run(stack):
    s = stack
    SOURCE.update({"a": [1], "b": [1], "c": [1]})
    gw = s.gateway("state-gw")
    await gw.sync()
    for k in SOURCE:
        SOURCE[k] = [1, 2]
    s.transport.fail_publishes = 1  # whichever document publishes first
    r = await gw.sync()

    assert (r.updated, len(r.errors)) == (2, 1)
    live = [k for k in SOURCE if (await s.doc(k))["body"]["items"] == [1, 2]]
    assert len(live) == 2


# ---------------------------------------------------------------------------
# draft_verdict
# ---------------------------------------------------------------------------


def test_draft_verdict():
    live = {"title": "T", "items": [1], "count": 1}
    owned = ("items", "count")
    assert draft_verdict(live, None, owned) == ("none", [])
    assert draft_verdict(live, {}, owned) == ("none", [])
    assert draft_verdict(live, {**live, "items": [1, 2], "count": 2.0}, owned) == (
        "gateway-only",
        ["count", "items"],
    )
    assert draft_verdict(live, {**live, "notes": "x"}, owned) == ("human-edits", ["notes"])
    # 2 and 2.0 are the same stored number.
    assert draft_verdict({"count": 2}, {"count": 2.0}, owned) == ("gateway-only", [])
    # A key the model drops on every write is not a person's edit when told to ignore it.
    assert (
        draft_verdict({**live, "draft": True}, live, owned, ignore=("draft",))[0] == "gateway-only"
    )
    # No declared ownership: nothing can be told apart.
    assert draft_verdict(live, {**live, "items": [2]}, None)[0] == "human-edits"


async def test_sync_range_still_overrides_the_default(stack):
    s = stack
    SOURCE["a"] = [1]
    gw = s.gateway("state-gw")
    await gw.sync()
    r = await gw.sync(SyncRange("all_time"))
    assert r.window.mode == "all_time" and not r.window.fell_back
