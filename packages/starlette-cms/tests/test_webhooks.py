"""
Tests for webhook CRUD endpoints and fire-and-forget delivery.

Uses ``respx`` to mock outbound httpx calls so delivery tests don't make
real HTTP requests.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import httpx
import pytest_asyncio
import respx
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wh_cms():
    """CMS instance with a PageDocument registered for webhook delivery tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

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
async def wh_client(wh_cms: CMS):
    """httpx.AsyncClient targeting wh_cms.app."""
    app = Starlette(routes=[Mount("/", app=wh_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def authed_wh_cms():
    """CMS with apikey auth for testing auth-protected webhook endpoints."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="apikey",
            api_key="wh-secret",
            read_auth=False,
        )

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
async def authed_wh_client(authed_wh_cms: CMS):
    """httpx.AsyncClient for the apikey-protected webhook CMS."""
    app = Starlette(routes=[Mount("/", app=authed_wh_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# CRUD: POST /api/webhooks
# ---------------------------------------------------------------------------


async def test_create_webhook_valid(wh_client):
    """POST with valid url + events returns 201 with the new webhook."""
    resp = await wh_client.post(
        "/api/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.published"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["document.published"]
    assert "id" in body
    assert body["active"] is True


async def test_create_webhook_missing_url(wh_client):
    """POST without url returns 422."""
    resp = await wh_client.post(
        "/api/webhooks",
        json={"events": ["document.published"]},
    )
    assert resp.status_code == 422
    assert "url" in resp.json()["error"]


async def test_create_webhook_missing_events(wh_client):
    """POST without events returns 422."""
    resp = await wh_client.post(
        "/api/webhooks",
        json={"url": "https://example.com/hook"},
    )
    assert resp.status_code == 422
    assert "events" in resp.json()["error"]


async def test_create_webhook_empty_events(wh_client):
    """POST with empty events list returns 422."""
    resp = await wh_client.post(
        "/api/webhooks",
        json={"url": "https://example.com/hook", "events": []},
    )
    assert resp.status_code == 422
    assert "events" in resp.json()["error"]


# ---------------------------------------------------------------------------
# CRUD: GET /api/webhooks
# ---------------------------------------------------------------------------


async def test_list_webhooks(wh_client):
    """GET /api/webhooks returns list of registered webhooks."""
    # Register two webhooks
    await wh_client.post(
        "/api/webhooks",
        json={"url": "https://a.example.com/hook", "events": ["document.created"]},
    )
    await wh_client.post(
        "/api/webhooks",
        json={"url": "https://b.example.com/hook", "events": ["document.updated"]},
    )

    resp = await wh_client.get("/api/webhooks")
    assert resp.status_code == 200
    body = resp.json()
    assert "webhooks" in body
    urls = [w["url"] for w in body["webhooks"]]
    assert "https://a.example.com/hook" in urls
    assert "https://b.example.com/hook" in urls


async def test_list_webhooks_empty(wh_client):
    """GET /api/webhooks returns an empty list when none registered."""
    resp = await wh_client.get("/api/webhooks")
    assert resp.status_code == 200
    assert resp.json()["webhooks"] == []


# ---------------------------------------------------------------------------
# CRUD: DELETE /api/webhooks/{id}
# ---------------------------------------------------------------------------


async def test_delete_webhook_valid(wh_client):
    """DELETE valid id returns 204 and the webhook is gone."""
    create_resp = await wh_client.post(
        "/api/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.published"]},
    )
    webhook_id = create_resp.json()["id"]

    delete_resp = await wh_client.delete(f"/api/webhooks/{webhook_id}")
    assert delete_resp.status_code == 204

    # Verify it's gone
    list_resp = await wh_client.get("/api/webhooks")
    ids = [w["id"] for w in list_resp.json()["webhooks"]]
    assert webhook_id not in ids


async def test_delete_webhook_missing(wh_client):
    """DELETE non-existent id returns 404."""
    resp = await wh_client.delete("/api/webhooks/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth: POST/DELETE require auth; GET respects read_auth=False
# ---------------------------------------------------------------------------


async def test_create_webhook_blocked_without_auth(authed_wh_client):
    """POST /api/webhooks returns 401 without auth header."""
    resp = await authed_wh_client.post(
        "/api/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.published"]},
    )
    assert resp.status_code == 401


async def test_create_webhook_allowed_with_auth(authed_wh_client):
    """POST /api/webhooks returns 201 with valid Bearer header."""
    resp = await authed_wh_client.post(
        "/api/webhooks",
        headers={"Authorization": "Bearer wh-secret"},
        json={"url": "https://example.com/hook", "events": ["document.published"]},
    )
    assert resp.status_code == 201


async def test_delete_webhook_blocked_without_auth(authed_wh_client):
    """DELETE /api/webhooks/{id} returns 401 without auth header."""
    # Create first via authed request so we have an id
    create_resp = await authed_wh_client.post(
        "/api/webhooks",
        headers={"Authorization": "Bearer wh-secret"},
        json={"url": "https://example.com/hook", "events": ["document.published"]},
    )
    webhook_id = create_resp.json()["id"]

    resp = await authed_wh_client.delete(f"/api/webhooks/{webhook_id}")
    assert resp.status_code == 401


async def test_get_webhooks_no_auth_required_by_default(authed_wh_client):
    """GET /api/webhooks succeeds without auth when read_auth=False."""
    resp = await authed_wh_client.get("/api/webhooks")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Delivery: fire_event dispatches to matching webhooks
# ---------------------------------------------------------------------------


async def test_delivery_matching_event(wh_client):
    """document.published fires to a webhook subscribed to that event."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/netlify").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/netlify", "events": ["document.published"]},
        )

        # Create a document then publish it
        create_resp = await wh_client.post(
            "/api/documents",
            json={"doc_type": "page", "slug": "hello", "body": {"title": "Hello", "slug": "hello"}},
        )
        doc_id = create_resp.json()["id"]

        await wh_client.post(f"/api/documents/{doc_id}/publish")

        # Allow fire-and-forget tasks to run: aiosqlite uses a thread-pool so
        # the DB query inside fire_event needs a real time quantum.
        await asyncio.sleep(0.1)

        assert mock.calls.call_count >= 1
        data = _json.loads(mock.calls.last.request.content)
        assert data["event"] == "document.published"
        assert data["document_id"] == doc_id
        assert data["document_type"] == "page"
        assert "timestamp" in data


async def test_delivery_non_matching_event(wh_client):
    """document.created does NOT fire to a webhook only subscribed to published."""
    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/netlify").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/netlify", "events": ["document.published"]},
        )

        # Create a document (document.created should not fire to this webhook)
        await wh_client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": "no-fire",
                "body": {"title": "No fire", "slug": "no-fire"},
            },
        )

        await asyncio.sleep(0.1)

        assert mock.calls.call_count == 0


async def test_delivery_document_created(wh_client):
    """document.created fires to matching webhook."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/created-hook").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/created-hook", "events": ["document.created"]},
        )

        await wh_client.post(
            "/api/documents",
            json={"doc_type": "page", "slug": "new", "body": {"title": "New", "slug": "new"}},
        )

        await asyncio.sleep(0.1)

        assert mock.calls.call_count == 1
        data = _json.loads(mock.calls.last.request.content)
        assert data["event"] == "document.created"


async def test_delivery_document_updated(wh_client):
    """document.updated fires to matching webhook."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/updated-hook").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/updated-hook", "events": ["document.updated"]},
        )

        create_resp = await wh_client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": "update-me",
                "body": {"title": "Before", "slug": "update-me"},
            },
        )
        doc_id = create_resp.json()["id"]

        await wh_client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"title": "After", "slug": "update-me"}},
        )

        await asyncio.sleep(0.1)

        assert mock.calls.call_count == 1
        data = _json.loads(mock.calls.last.request.content)
        assert data["event"] == "document.updated"


async def test_delivery_document_deleted(wh_client):
    """document.deleted fires to matching webhook."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/deleted-hook").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/deleted-hook", "events": ["document.deleted"]},
        )

        create_resp = await wh_client.post(
            "/api/documents",
            json={"doc_type": "page", "slug": "bye", "body": {"title": "Bye", "slug": "bye"}},
        )
        doc_id = create_resp.json()["id"]

        await wh_client.delete(f"/api/documents/{doc_id}")

        await asyncio.sleep(0.1)

        assert mock.calls.call_count == 1
        data = _json.loads(mock.calls.last.request.content)
        assert data["event"] == "document.deleted"


async def test_delivery_document_unpublished(wh_client):
    """document.unpublished fires to matching webhook."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/unpub-hook").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={
                "url": "https://hooks.example.com/unpub-hook",
                "events": ["document.unpublished"],
            },
        )

        create_resp = await wh_client.post(
            "/api/documents",
            json={"doc_type": "page", "slug": "unpub", "body": {"title": "Unpub", "slug": "unpub"}},
        )
        doc_id = create_resp.json()["id"]

        await wh_client.post(f"/api/documents/{doc_id}/publish")
        await wh_client.post(f"/api/documents/{doc_id}/unpublish")

        await asyncio.sleep(0.1)

        calls_events = [_json.loads(c.request.content)["event"] for c in mock.calls]
        assert "document.unpublished" in calls_events


async def test_delivery_payload_shape(wh_client):
    """Delivery payload contains event, document_id, document_type, slug, timestamp."""
    import json as _json

    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/shape-hook").mock(return_value=httpx.Response(200))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/shape-hook", "events": ["document.published"]},
        )

        create_resp = await wh_client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": "payload-test",
                "body": {"title": "Shape", "slug": "payload-test"},
            },
        )
        doc_id = create_resp.json()["id"]
        await wh_client.post(f"/api/documents/{doc_id}/publish")

        await asyncio.sleep(0.1)

        assert mock.calls.call_count >= 1
        payload = _json.loads(mock.calls.last.request.content)
        assert payload["event"] == "document.published"
        assert payload["document_id"] == doc_id
        assert payload["document_type"] == "page"
        assert payload["slug"] == "payload-test"
        assert "timestamp" in payload


async def test_delivery_failure_does_not_affect_response(wh_client):
    """Failed delivery (500 from endpoint) does not affect the document API response."""
    with respx.mock(base_url="https://hooks.example.com", assert_all_called=False) as mock:
        mock.post("/failing-hook").mock(return_value=httpx.Response(500))

        await wh_client.post(
            "/api/webhooks",
            json={"url": "https://hooks.example.com/failing-hook", "events": ["document.created"]},
        )

        create_resp = await wh_client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": "resilient",
                "body": {"title": "Resilient", "slug": "resilient"},
            },
        )

        # The document API still returns 201 even though the webhook returned 500
        assert create_resp.status_code == 201

        await asyncio.sleep(0.1)
