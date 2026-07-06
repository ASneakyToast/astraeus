"""
Tests for Phase NS-1A: dual-state (draft_body / published body) document support.

All 12 acceptance tests from the spec:

 1. PATCH creates a draft — body unchanged, draft_body contains patched fields,
    has_draft=true
 2. PATCH on document with no prior draft initialises draft from published body
 3. GET without ?draft=true returns published body (not draft)
 4. GET with ?draft=true returns draft_body when draft exists
 5. GET with ?draft=true on doc with no draft returns published body
 6. List response includes has_draft field on every item
 7. List ?has_draft=true filter returns only docs with drafts
 8. Publish copies draft → body, clears draft, has_draft=false after
 9. Publish with no draft re-publishes same content (no-op body change,
    still sets published=true)
10. Discard draft: draft_body cleared, GET returns published body, has_draft=false
11. draft_version increments on each PATCH
12. draft_version resets to 0 on publish and discard
"""

from __future__ import annotations

import os
import tempfile

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, TextField


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def draft_client():
    """
    CMS with a single ``article`` document type.  Returns an httpx.AsyncClient
    and the CMS instance as a tuple.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

        @instance.document("article")
        class Article:
            title: str = TextField(required=True)
            body_text: str = TextField(required=False)

        async with instance.lifespan_context(None):
            app = Starlette(routes=[Mount("/", app=instance.app)])
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as c:
                yield c, instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_article(client: httpx.AsyncClient, title: str, body_text: str = "") -> str:
    """Create an article document and return its id."""
    payload: dict = {"doc_type": "article", "body": {"title": title}}
    if body_text:
        payload["body"]["body_text"] = body_text
    resp = await client.post("/api/documents", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Test 1 — PATCH creates a draft; published body is unchanged
# ---------------------------------------------------------------------------


async def test_patch_creates_draft_body_unchanged(draft_client):
    """PATCH writes to draft_body; the published body field is unaffected."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Original Title", "Original body")

    patch_resp = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Drafted Title", "body_text": "Original body"}},
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["has_draft"] is True

    # Published body should still reflect original content
    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["body"]["title"] == "Original Title"
    assert get_resp.json()["has_draft"] is True


# ---------------------------------------------------------------------------
# Test 2 — PATCH on doc with no prior draft seeds draft from published body
# ---------------------------------------------------------------------------


async def test_patch_initialises_draft_from_published_body(draft_client):
    """First PATCH initialises draft by merging into a copy of the published body."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Published Title", "Published body text")

    # Patch only the title — body_text should appear in draft (seeded from published)
    patch_resp = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "New Title", "body_text": "Published body text"}},
    )
    assert patch_resp.status_code == 200

    # Reading draft should contain both fields
    draft_resp = await client.get(f"/api/documents/{doc_id}?draft=true")
    assert draft_resp.status_code == 200
    draft_body = draft_resp.json()["body"]
    assert draft_body["title"] == "New Title"
    assert draft_body["body_text"] == "Published body text"


# ---------------------------------------------------------------------------
# Test 3 — GET without ?draft=true returns published body
# ---------------------------------------------------------------------------


async def test_get_without_draft_param_returns_published_body(draft_client):
    """GET (no query param) always returns the published body, not the draft."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Stable Title")

    await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Draft Title", "body_text": ""}},
    )

    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["body"]["title"] == "Stable Title"


# ---------------------------------------------------------------------------
# Test 4 — GET with ?draft=true returns draft_body when draft exists
# ---------------------------------------------------------------------------


async def test_get_with_draft_param_returns_draft_body(draft_client):
    """GET ?draft=true returns draft_body content when a draft exists."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Original")

    await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Drafted Version", "body_text": ""}},
    )

    resp = await client.get(f"/api/documents/{doc_id}?draft=true")
    assert resp.status_code == 200
    assert resp.json()["body"]["title"] == "Drafted Version"
    assert resp.json()["has_draft"] is True


# ---------------------------------------------------------------------------
# Test 5 — GET with ?draft=true on doc with no draft returns published body
# ---------------------------------------------------------------------------


async def test_get_with_draft_param_no_draft_falls_back_to_published(draft_client):
    """GET ?draft=true falls back to published body when no draft exists."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "No Draft Here")

    resp = await client.get(f"/api/documents/{doc_id}?draft=true")
    assert resp.status_code == 200
    assert resp.json()["body"]["title"] == "No Draft Here"
    assert resp.json()["has_draft"] is False


# ---------------------------------------------------------------------------
# Test 6 — List response includes has_draft on every item
# ---------------------------------------------------------------------------


async def test_list_includes_has_draft_on_every_item(draft_client):
    """Every document in the list response includes has_draft."""
    client, _cms = draft_client

    id1 = await _create_article(client, "Doc A")
    id2 = await _create_article(client, "Doc B")

    # Give id1 a draft
    await client.patch(
        f"/api/documents/{id1}",
        json={"body": {"title": "Doc A Draft", "body_text": ""}},
    )

    resp = await client.get("/api/documents?type=article")
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert len(docs) >= 2

    for doc in docs:
        assert "has_draft" in doc

    doc_map = {d["id"]: d for d in docs}
    assert doc_map[id1]["has_draft"] is True
    assert doc_map[id2]["has_draft"] is False


# ---------------------------------------------------------------------------
# Test 7 — List ?has_draft=true returns only docs with drafts
# ---------------------------------------------------------------------------


async def test_list_has_draft_filter(draft_client):
    """?has_draft=true returns only documents where draft_body is non-null."""
    client, _cms = draft_client

    id_with_draft = await _create_article(client, "Has Draft")
    _id_without = await _create_article(client, "No Draft")

    await client.patch(
        f"/api/documents/{id_with_draft}",
        json={"body": {"title": "Has Draft Modified", "body_text": ""}},
    )

    resp = await client.get("/api/documents?has_draft=true")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()["documents"]]
    assert id_with_draft in ids
    assert _id_without not in ids


# ---------------------------------------------------------------------------
# Test 8 — Publish copies draft → body, clears draft
# ---------------------------------------------------------------------------


async def test_publish_promotes_draft_to_body(draft_client):
    """Publishing a document with a draft promotes draft_body to body and clears draft."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Pre-publish")

    await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Drafted for Publish", "body_text": ""}},
    )

    pub_resp = await client.post(f"/api/documents/{doc_id}/publish")
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()
    assert pub_data["published"] is True
    assert pub_data["has_draft"] is False
    assert pub_data["draft_version"] == 0

    # Body should now reflect the formerly-drafted content
    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.json()["body"]["title"] == "Drafted for Publish"
    assert get_resp.json()["has_draft"] is False


# ---------------------------------------------------------------------------
# Test 9 — Publish with no draft re-publishes same content
# ---------------------------------------------------------------------------


async def test_publish_without_draft_republishes_same_content(draft_client):
    """Publish on a document with no draft still sets published=true."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Stable Content")

    pub_resp = await client.post(f"/api/documents/{doc_id}/publish")
    assert pub_resp.status_code == 200
    data = pub_resp.json()
    assert data["published"] is True
    assert data["has_draft"] is False
    assert data["body"]["title"] == "Stable Content"


# ---------------------------------------------------------------------------
# Test 10 — Discard draft clears draft_body; GET returns published body
# ---------------------------------------------------------------------------


async def test_discard_draft_clears_draft(draft_client):
    """POST /discard-draft sets draft_body=null; subsequent GET returns published body."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Keep This")

    await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Discard Me", "body_text": ""}},
    )

    # Confirm draft is present
    assert (await client.get(f"/api/documents/{doc_id}")).json()["has_draft"] is True

    discard_resp = await client.post(f"/api/documents/{doc_id}/discard-draft")
    assert discard_resp.status_code == 200
    discard_data = discard_resp.json()
    assert discard_data["has_draft"] is False
    assert discard_data["body"]["title"] == "Keep This"

    # Confirm via GET
    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.json()["has_draft"] is False
    assert get_resp.json()["body"]["title"] == "Keep This"


# ---------------------------------------------------------------------------
# Test 11 — draft_version increments on each PATCH
# ---------------------------------------------------------------------------


async def test_draft_version_increments_on_each_patch(draft_client):
    """draft_version increases by 1 with each successful PATCH."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Version Test")

    # First PATCH
    r1 = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "V1", "body_text": ""}},
    )
    assert r1.status_code == 200
    assert r1.json()["draft_version"] == 1

    # Second PATCH
    r2 = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "V2", "body_text": ""}},
    )
    assert r2.status_code == 200
    assert r2.json()["draft_version"] == 2

    # Third PATCH
    r3 = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "V3", "body_text": ""}},
    )
    assert r3.status_code == 200
    assert r3.json()["draft_version"] == 3


# ---------------------------------------------------------------------------
# Test 12 — draft_version resets to 0 on publish and discard
# ---------------------------------------------------------------------------


async def test_draft_version_resets_on_publish_and_discard(draft_client):
    """draft_version returns to 0 after publish or discard-draft."""
    client, _cms = draft_client

    doc_id = await _create_article(client, "Reset Test")

    # Build up a non-zero draft_version
    for i in range(3):
        await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"title": f"Draft {i}", "body_text": ""}},
        )

    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.json()["draft_version"] == 3

    # Publish — version should reset
    pub_resp = await client.post(f"/api/documents/{doc_id}/publish")
    assert pub_resp.status_code == 200
    assert pub_resp.json()["draft_version"] == 0

    # Build it up again
    for i in range(2):
        await client.patch(
            f"/api/documents/{doc_id}",
            json={"body": {"title": f"Post-publish draft {i}", "body_text": ""}},
        )

    assert (await client.get(f"/api/documents/{doc_id}")).json()["draft_version"] == 2

    # Discard — version should reset
    discard_resp = await client.post(f"/api/documents/{doc_id}/discard-draft")
    assert discard_resp.status_code == 200
    assert discard_resp.json()["draft_version"] == 0
