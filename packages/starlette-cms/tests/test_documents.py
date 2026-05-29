"""Full CRUD tests for the document endpoints."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# List documents
# ---------------------------------------------------------------------------


async def test_list_documents_empty(client):
    resp = await client.get("/api/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["documents"] == []
    assert data["total"] == 0


async def test_list_documents_filter_by_type(client):
    # Create two documents of different types
    await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "home", "body": {"title": "Home", "slug": "home"}},
    )
    resp = await client.get("/api/documents?type=page")
    assert resp.status_code == 200
    data = resp.json()
    assert all(d["doc_type"] == "page" for d in data["documents"])


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_document(client):
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "about", "body": {"title": "About", "slug": "about"}},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["doc_type"] == "page"
    assert data["slug"] == "about"
    assert "id" in data
    assert data["published"] is False


async def test_create_document_unknown_type_returns_422(client):
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "unknown_type", "body": {"title": "x"}},
    )
    assert resp.status_code == 422


async def test_create_document_invalid_body_returns_422(client):
    # Missing required 'title' field
    resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "body": {"slug": "only-slug"}},
    )
    assert resp.status_code == 422


async def test_create_document_missing_doc_type_returns_422(client):
    resp = await client.post(
        "/api/documents",
        json={"body": {"title": "x", "slug": "x"}},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


async def test_get_document(client):
    create_resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "blog", "body": {"title": "Blog", "slug": "blog"}},
    )
    doc_id = create_resp.json()["id"]

    resp = await client.get(f"/api/documents/{doc_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


async def test_get_document_not_found(client):
    resp = await client.get("/api/documents/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------


async def test_patch_document(client):
    create_resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "page",
            "slug": "contact",
            "body": {"title": "Contact", "slug": "contact"},
        },
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"title": "Updated Contact", "slug": "contact"}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["title"] == "Updated Contact"


async def test_patch_document_not_found(client):
    resp = await client.patch(
        "/api/documents/bad-id",
        json={"body": {"title": "x", "slug": "x"}},
    )
    assert resp.status_code == 404


async def test_patch_updates_slug(client):
    create_resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "old-slug", "body": {"title": "T", "slug": "t"}},
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/documents/{doc_id}",
        json={"slug": "new-slug"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["slug"] == "new-slug"


# ---------------------------------------------------------------------------
# Publish / unpublish
# ---------------------------------------------------------------------------


async def test_publish_document(client):
    create_resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "news", "body": {"title": "News", "slug": "news"}},
    )
    doc_id = create_resp.json()["id"]

    pub_resp = await client.post(f"/api/documents/{doc_id}/publish")
    assert pub_resp.status_code == 200
    data = pub_resp.json()
    assert data["published"] is True
    assert data["published_at"] is not None


async def test_unpublish_document(client):
    create_resp = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "draft", "body": {"title": "Draft", "slug": "draft"}},
    )
    doc_id = create_resp.json()["id"]

    await client.post(f"/api/documents/{doc_id}/publish")

    unpub_resp = await client.post(f"/api/documents/{doc_id}/unpublish")
    assert unpub_resp.status_code == 200
    assert unpub_resp.json()["published"] is False


async def test_publish_not_found(client):
    resp = await client.post("/api/documents/no-such-id/publish")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def test_delete_document(client):
    create_resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "page",
            "slug": "todelete",
            "body": {"title": "Delete Me", "slug": "todelete"},
        },
    )
    doc_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/documents/{doc_id}")
    assert del_resp.status_code == 204

    # Confirm gone
    get_resp = await client.get(f"/api/documents/{doc_id}")
    assert get_resp.status_code == 404


async def test_delete_not_found(client):
    resp = await client.delete("/api/documents/ghost-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


async def test_filter_by_published(client):
    # Create two docs, publish one
    r1 = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "p1", "body": {"title": "P1", "slug": "p1"}},
    )
    r2 = await client.post(
        "/api/documents",
        json={"doc_type": "page", "slug": "p2", "body": {"title": "P2", "slug": "p2"}},
    )
    await client.post(f"/api/documents/{r1.json()['id']}/publish")

    resp = await client.get("/api/documents?published=true")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()["documents"]]
    assert r1.json()["id"] in ids
    assert r2.json()["id"] not in ids


async def test_pagination(client):
    # Create 3 documents
    for i in range(3):
        await client.post(
            "/api/documents",
            json={
                "doc_type": "page",
                "slug": f"page-{i}",
                "body": {"title": f"Page {i}", "slug": f"page-{i}"},
            },
        )

    resp = await client.get("/api/documents?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["documents"]) == 2
    assert data["total"] >= 3
