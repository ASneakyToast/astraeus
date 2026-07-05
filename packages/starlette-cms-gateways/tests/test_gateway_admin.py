"""
Tests for the GatewayAdmin — API routes and shell page.

Uses a real in-process CMS (same pattern as test_sync_e2e.py) and patches
entry-point discovery so the tests don't depend on any installed gateways.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField
from starlette_cms.fields import NumberField
from starlette_cms_gateways.admin import GatewayAdmin
from starlette_cms_gateways.base import BaseGateway, GatewayItem


# ---------------------------------------------------------------------------
# Minimal test gateway (mirrors test_sync_e2e.py)
# ---------------------------------------------------------------------------

_ADMIN_FAKE_DB: list[dict] = []


class AdminTestGateway(BaseGateway):
    service_name = "admin_test_service"
    block_type = "admin_test_item"
    auto_publish = True

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        for entry in _ADMIN_FAKE_DB:
            yield GatewayItem(
                import_ref=f"admin_test:item:{entry['id']}",
                slug=f"admin-test-{entry['id']}",
                body={"name": entry["name"]},
            )


_FAKE_ENTRY_POINTS = {"admin-test": AdminTestGateway}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def admin_app():
    """
    Spin up a CMS + GatewayAdmin with an in-process ASGI client.

    Yields a dict with:
      - ``client``: httpx.AsyncClient routed through the full Starlette app
      - ``cms``: the CMS instance (for direct inspection)
      - ``admin``: the GatewayAdmin instance
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        cms_instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="apikey",
            api_key="test-secret",
            mount_path="/cms",
        )

        @cms_instance.block("admin_test_item")
        class AdminTestItemBlock:
            name: str = TextField(required=True)

        admin_instance = GatewayAdmin(cms=cms_instance)

        root = Starlette(
            routes=[
                Mount("/cms", app=cms_instance.app),
                Mount("/gateways", app=admin_instance.app),
            ]
        )

        async with cms_instance.lifespan_context(None):
            transport = ASGITransport(app=root)
            client = httpx.AsyncClient(
                transport=transport,
                base_url="http://testserver",
            )
            try:
                yield {"client": client, "cms": cms_instance, "admin": admin_instance}
            finally:
                await client.aclose()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-secret"}


# ---------------------------------------------------------------------------
# Shell tests
# ---------------------------------------------------------------------------


async def test_shell_returns_html(admin_app):
    """GET /gateways/shell should return an HTML page."""
    resp = await admin_app["client"].get("/gateways/shell")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Gateway Admin" in resp.text
    assert "__GATEWAY_CONFIG__" not in resp.text  # uses inline var, not window config
    # The JS config must inject the correct CMS base path
    assert "/cms" in resp.text


# ---------------------------------------------------------------------------
# GET /cms/api/gateways
# ---------------------------------------------------------------------------


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_list_gateways(mock_disc, admin_app):
    """GET /api/gateways returns all installed gateways."""
    resp = await admin_app["client"].get("/cms/api/gateways")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    gw = data["gateways"][0]
    assert gw["name"] == "admin-test"
    assert gw["service_name"] == "admin_test_service"
    assert gw["block_type"] == "admin_test_item"
    assert gw["auto_publish"] is True


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value={},
)
async def test_list_gateways_empty(mock_disc, admin_app):
    """Returns an empty list when no gateways are installed."""
    resp = await admin_app["client"].get("/cms/api/gateways")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ---------------------------------------------------------------------------
# GET /cms/api/gateways/{name}
# ---------------------------------------------------------------------------


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_get_gateway_found(mock_disc, admin_app):
    resp = await admin_app["client"].get("/cms/api/gateways/admin-test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "admin-test"
    assert "recent_jobs" in data


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_get_gateway_not_found(mock_disc, admin_app):
    resp = await admin_app["client"].get("/cms/api/gateways/no-such-gateway")
    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


# ---------------------------------------------------------------------------
# POST /cms/api/gateways/{name}/sync
# ---------------------------------------------------------------------------


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_trigger_sync_returns_202(mock_disc, admin_app):
    """POST /api/gateways/{name}/sync returns 202 immediately."""
    global _ADMIN_FAKE_DB
    _ADMIN_FAKE_DB = [{"id": "1", "name": "Alpha"}]

    resp = await admin_app["client"].post(
        "/cms/api/gateways/admin-test/sync",
        headers=_auth_headers(),
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "running"
    assert "run_id" in data
    assert "poll_url" in data


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_trigger_sync_requires_auth(mock_disc, admin_app):
    """POST without auth header should return 401."""
    resp = await admin_app["client"].post("/cms/api/gateways/admin-test/sync")
    assert resp.status_code == 401


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_trigger_sync_unknown_gateway(mock_disc, admin_app):
    resp = await admin_app["client"].post(
        "/cms/api/gateways/nonexistent/sync",
        headers=_auth_headers(),
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /cms/api/gateways/{name}/sync/{run_id} — poll
# ---------------------------------------------------------------------------


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_poll_job_not_found(mock_disc, admin_app):
    resp = await admin_app["client"].get(
        "/cms/api/gateways/admin-test/sync/nonexistent-run-id"
    )
    assert resp.status_code == 404


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_trigger_and_poll_sync_to_done(mock_disc, admin_app):
    """
    Trigger a sync, receive a run_id, then poll until the job is done.

    The sync itself runs as an asyncio.Task; by the time poll requests land the
    task may still be running.  We retry polling up to 10 times with a short
    sleep to give the task time to finish.
    """
    import asyncio

    global _ADMIN_FAKE_DB
    _ADMIN_FAKE_DB = [{"id": "P1", "name": "PollTest"}]

    # Kick off sync
    trigger_resp = await admin_app["client"].post(
        "/cms/api/gateways/admin-test/sync",
        headers=_auth_headers(),
    )
    assert trigger_resp.status_code == 202
    run_id = trigger_resp.json()["run_id"]

    # Poll until done (or timeout after ~5s)
    final: dict = {}
    for _ in range(20):
        await asyncio.sleep(0.25)
        poll_resp = await admin_app["client"].get(
            f"/cms/api/gateways/admin-test/sync/{run_id}"
        )
        assert poll_resp.status_code == 200
        final = poll_resp.json()
        if final["status"] != "running":
            break

    assert final["status"] == "done", f"Job did not finish: {final}"
    result = final["result"]
    assert result["created"] == 1
    assert result["errors"] == []


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_second_sync_skips_identical(mock_disc, admin_app):
    """Run the same sync twice; second run should skip all docs."""
    import asyncio

    global _ADMIN_FAKE_DB
    _ADMIN_FAKE_DB = [{"id": "S1", "name": "SkipMe"}]

    async def _sync_and_wait() -> dict:
        resp = await admin_app["client"].post(
            "/cms/api/gateways/admin-test/sync",
            headers=_auth_headers(),
        )
        run_id = resp.json()["run_id"]
        for _ in range(20):
            await asyncio.sleep(0.25)
            poll = await admin_app["client"].get(
                f"/cms/api/gateways/admin-test/sync/{run_id}"
            )
            data = poll.json()
            if data["status"] != "running":
                return data
        return {}

    r1 = await _sync_and_wait()
    assert r1["status"] == "done"
    assert r1["result"]["created"] == 1

    r2 = await _sync_and_wait()
    assert r2["status"] == "done"
    assert r2["result"]["skipped"] == 1
    assert r2["result"]["created"] == 0


@patch(
    "starlette_cms_gateways.admin.api.discover_gateways",
    return_value=_FAKE_ENTRY_POINTS,
)
async def test_job_persisted_in_cms(mock_disc, admin_app):
    """
    Job records are stored as CMS documents, not in-memory.

    After a sync completes, the run_id is still resolvable via the poll
    endpoint — proving the result came from the database, not a dict that
    would be cleared on restart.  We verify by also fetching the job document
    directly from the CMS documents API.
    """
    import asyncio

    global _ADMIN_FAKE_DB
    _ADMIN_FAKE_DB = [{"id": "PERSIST1", "name": "Persistent"}]

    resp = await admin_app["client"].post(
        "/cms/api/gateways/admin-test/sync",
        headers=_auth_headers(),
    )
    run_id = resp.json()["run_id"]

    # Wait for completion
    final: dict = {}
    for _ in range(20):
        await asyncio.sleep(0.25)
        poll = await admin_app["client"].get(
            f"/cms/api/gateways/admin-test/sync/{run_id}"
        )
        final = poll.json()
        if final["status"] != "running":
            break

    assert final["status"] == "done"

    # Confirm the job start document exists in the CMS documents API
    docs_resp = await admin_app["client"].get(
        f"/cms/api/documents?type=gateway_sync_job&import_ref=gateway_sync_job:{run_id}",
        headers=_auth_headers(),
    )
    assert docs_resp.status_code == 200
    docs = docs_resp.json().get("documents", [])
    assert len(docs) == 1, "Job start document should be stored in the CMS"
    assert docs[0]["body"]["gateway_name"] == "admin-test"
    assert docs[0]["body"]["status"] == "running"  # start doc always says running
