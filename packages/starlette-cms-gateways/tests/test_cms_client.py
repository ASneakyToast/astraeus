"""
Tests for CMSClient — upsert create/update/skip logic, mocked via respx.

These tests never spin up a real CMS — all HTTP calls are intercepted by
respx and return carefully crafted mock responses.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from starlette_cms_gateways.base import GatewayItem
from starlette_cms_gateways.client import CMSClient, CMSError

BASE = "http://testcms"


def _make_client() -> CMSClient:
    """Return a CMSClient backed by a shared httpx.AsyncClient for test interception."""
    return CMSClient(base_url=BASE, api_key="test-key")


def _doc(
    doc_id: str = "doc123",
    import_ref: str = "svc:type:001",
    body: dict | None = None,
    published: bool = False,
    content_hash: str | None = None,
) -> dict:
    """Build a fake CMS document dict."""
    meta: dict = {}
    if content_hash:
        meta["content_hash"] = content_hash
    return {
        "id": doc_id,
        "doc_type": "my_block",
        "slug": "test-slug",
        "import_ref": import_ref,
        "body": body or {"title": "Test"},
        "meta": meta,
        "published": published,
    }


def _list_resp(docs: list[dict]) -> dict:
    return {"documents": docs, "total": len(docs)}


# ---------------------------------------------------------------------------
# find_by_import_ref
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_find_by_import_ref_returns_doc():
    doc = _doc()
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([doc]))
        )
        client = _make_client()
        result = await client.find_by_import_ref("my_block", "svc:type:001")
    assert result is not None
    assert result["id"] == "doc123"


@pytest.mark.anyio
async def test_find_by_import_ref_returns_none_when_not_found():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([]))
        )
        client = _make_client()
        result = await client.find_by_import_ref("my_block", "svc:type:MISSING")
    assert result is None


@pytest.mark.anyio
async def test_find_by_import_ref_raises_on_error():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        client = _make_client()
        with pytest.raises(CMSError) as exc_info:
            await client.find_by_import_ref("my_block", "svc:type:001")
    assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# upsert — create path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_creates_new_document():
    """When no existing doc found, creates and returns 'created'."""
    item = GatewayItem(
        import_ref="svc:type:NEW",
        slug="new-doc",
        body={"title": "New"},
    )
    created_doc = _doc(doc_id="new001", import_ref="svc:type:NEW")

    with respx.mock(base_url=BASE) as mock:
        # find_by_import_ref → empty
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([]))
        )
        # create
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json=created_doc)
        )
        # publish
        mock.post(f"/api/documents/new001/publish").mock(
            return_value=httpx.Response(200, json={**created_doc, "published": True})
        )

        client = _make_client()
        action = await client.upsert(item=item, block_type="my_block", auto_publish=True)

    assert action == "created"


@pytest.mark.anyio
async def test_upsert_create_without_publish_when_auto_publish_false():
    """auto_publish=False — create call should not be followed by publish call."""
    item = GatewayItem(import_ref="svc:type:NOPUB", slug="no-pub", body={"title": "X"})
    created_doc = _doc(doc_id="nopub01", import_ref="svc:type:NOPUB")

    publish_called = False

    with respx.mock(base_url=BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([]))
        )
        mock.post("/api/documents").mock(
            return_value=httpx.Response(201, json=created_doc)
        )

        def _record_publish(request):
            nonlocal publish_called
            publish_called = True
            return httpx.Response(200, json={})

        mock.post("/api/documents/nopub01/publish").mock(side_effect=_record_publish)

        client = _make_client()
        action = await client.upsert(item=item, block_type="my_block", auto_publish=False)

    assert action == "created"
    assert not publish_called


# ---------------------------------------------------------------------------
# upsert — skip path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_skips_when_hash_unchanged():
    """Existing doc with matching content_hash → skip, no PATCH call."""
    item = GatewayItem(
        import_ref="svc:type:SAME",
        slug="same-doc",
        body={"title": "Same"},
    )
    existing = _doc(
        doc_id="same001",
        import_ref="svc:type:SAME",
        body={"title": "Same"},
        content_hash=item.content_hash(),
    )

    patch_called = False

    # Use assert_all_called=False since the registered PATCH route must not be called
    with respx.mock(base_url=BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([existing]))
        )

        def _record_patch(request):
            nonlocal patch_called
            patch_called = True
            return httpx.Response(200, json={})

        mock.patch("/api/documents/same001").mock(side_effect=_record_patch)

        client = _make_client()
        action = await client.upsert(item=item, block_type="my_block", auto_publish=True)

    assert action == "skipped"
    assert not patch_called


# ---------------------------------------------------------------------------
# upsert — update path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_upsert_updates_when_hash_changed():
    """Existing doc with different content_hash → update, returns 'updated'."""
    item = GatewayItem(
        import_ref="svc:type:CHANGED",
        slug="changed-doc",
        body={"title": "New Title"},
    )
    existing = _doc(
        doc_id="upd001",
        import_ref="svc:type:CHANGED",
        body={"title": "Old Title"},
        content_hash="stale_hash_xxxx",  # won't match item.content_hash()
    )
    updated_doc = _doc(
        doc_id="upd001",
        import_ref="svc:type:CHANGED",
        body={"title": "New Title"},
        content_hash=item.content_hash(),
    )

    with respx.mock(base_url=BASE, assert_all_mocked=False, assert_all_called=False) as mock:
        mock.get("/api/documents").mock(
            return_value=httpx.Response(200, json=_list_resp([existing]))
        )
        mock.patch("/api/documents/upd001").mock(
            return_value=httpx.Response(200, json=updated_doc)
        )
        # existing doc is unpublished → upsert will call publish too
        mock.post("/api/documents/upd001/publish").mock(
            return_value=httpx.Response(200, json={**updated_doc, "published": True})
        )

        client = _make_client()
        action = await client.upsert(item=item, block_type="my_block", auto_publish=True)

    assert action == "updated"


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_auth_header_sent_on_requests():
    """Bearer token is attached to all requests."""
    sent_headers = {}

    with respx.mock(base_url=BASE) as mock:
        def _capture(request):
            sent_headers.update(dict(request.headers))
            return httpx.Response(200, json=_list_resp([]))

        mock.get("/api/documents").mock(side_effect=_capture)
        client = CMSClient(base_url=BASE, api_key="my-key")
        await client.find_by_import_ref("block", "ref")

    assert sent_headers.get("authorization") == "Bearer my-key"


# ---------------------------------------------------------------------------
# get_last_synced
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_last_synced_returns_none_when_404():
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents/singleton/gateway_sync_state").mock(
            return_value=httpx.Response(404, json={"error": "not found"})
        )
        client = _make_client()
        result = await client.get_last_synced("spotify_liked_songs")
    assert result is None


@pytest.mark.anyio
async def test_get_last_synced_returns_datetime():
    state_body = {
        "services": {
            "spotify_liked_songs": {
                "last_synced": "2026-06-19T12:00:00+00:00",
            }
        }
    }
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents/singleton/gateway_sync_state").mock(
            return_value=httpx.Response(
                200,
                json={"id": "s1", "body": state_body, "published": True},
            )
        )
        client = _make_client()
        result = await client.get_last_synced("spotify_liked_songs")
    assert result is not None
    assert result.year == 2026
    assert result.month == 6
    assert result.day == 19


@pytest.mark.anyio
async def test_get_last_synced_returns_none_for_unknown_service():
    state_body = {"services": {"other_service": {"last_synced": "2026-01-01T00:00:00+00:00"}}}
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/documents/singleton/gateway_sync_state").mock(
            return_value=httpx.Response(
                200,
                json={"id": "s1", "body": state_body, "published": True},
            )
        )
        client = _make_client()
        result = await client.get_last_synced("unknown_service")
    assert result is None
