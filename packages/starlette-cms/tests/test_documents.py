"""Full CRUD tests for the document endpoints."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, DocumentRef, TextField

# ---------------------------------------------------------------------------
# Singleton fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def singleton_cms():
    """CMS with a singleton block (storage_rates) and a regular block registered."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

        @instance.block("storage_rates", singleton=True)
        class StorageRates:
            bank_vault: str = TextField(label="Bank Vault Rate", required=True)
            home_safe: str = TextField(label="Home Safe Rate", required=True)

        @instance.block("jewelry_item")
        class JewelryItem:
            name: str = TextField(required=True)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def singleton_client(singleton_cms: CMS):
    """httpx.AsyncClient targeting singleton_cms.app."""
    app = Starlette(routes=[Mount("/", app=singleton_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


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


# ---------------------------------------------------------------------------
# Immutable fields
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def immutable_client():
    """CMS with a document type that mixes immutable and mutable fields."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none")

        @instance.document("entry")
        class Entry:
            ref: str = TextField(required=True, immutable=True)
            score: str = TextField(required=True)
            notes: str = TextField(required=False)

        app = Starlette(routes=[Mount("/", app=instance.app)])
        async with instance.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as c:
                yield c
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


async def test_immutable_field_ignored_on_patch(immutable_client):
    """PATCH with an immutable field returns 200 but the field value is unchanged."""
    create_resp = await immutable_client.post(
        "/api/documents",
        json={"doc_type": "entry", "slug": "e1", "body": {"ref": "orig", "score": "3"}},
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    patch_resp = await immutable_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"ref": "changed", "score": "5"}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["ref"] == "orig"
    assert body["score"] == "5"


async def test_immutable_field_written_on_create(immutable_client):
    """Immutable fields are written normally at create time."""
    resp = await immutable_client.post(
        "/api/documents",
        json={"doc_type": "entry", "slug": "e2", "body": {"ref": "created-ref", "score": "4"}},
    )
    assert resp.status_code == 201
    assert resp.json()["body"]["ref"] == "created-ref"


async def test_mutable_fields_still_patchable(immutable_client):
    """Non-immutable fields on a document with immutable fields update correctly."""
    create_resp = await immutable_client.post(
        "/api/documents",
        json={
            "doc_type": "entry",
            "slug": "e3",
            "body": {"ref": "fixed-ref", "score": "1", "notes": "first"},
        },
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await immutable_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"score": "5", "notes": "revised"}},
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()["body"]
    assert body["ref"] == "fixed-ref"
    assert body["score"] == "5"
    assert body["notes"] == "revised"


async def test_immutable_on_non_block_field(immutable_client):
    """TextField(immutable=True) strips the field correctly on PATCH."""
    create_resp = await immutable_client.post(
        "/api/documents",
        json={"doc_type": "entry", "slug": "e4", "body": {"ref": "text-ref", "score": "2"}},
    )
    doc_id = create_resp.json()["id"]

    patch_resp = await immutable_client.patch(
        f"/api/documents/{doc_id}",
        json={"body": {"ref": "new-text-ref"}},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["body"]["ref"] == "text-ref"


# ---------------------------------------------------------------------------
# Singleton documents
# ---------------------------------------------------------------------------


async def test_get_singleton_404_when_none_published(singleton_client):
    """GET singleton returns 404 before first publish."""
    resp = await singleton_client.get("/api/documents/singleton/storage_rates")
    assert resp.status_code == 404


async def test_publish_singleton_endpoint(singleton_client):
    """POST /api/documents/singleton/{type} creates + publishes in one step."""
    resp = await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={
            "body": {"bank_vault": "0.004", "home_safe": "0.010"},
            "version_message": "Initial rates",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["doc_type"] == "storage_rates"
    assert data["published"] is True
    assert data["singleton_status"] == "active"
    assert data["body"]["bank_vault"] == "0.004"


async def test_get_singleton_returns_active(singleton_client):
    """GET /api/documents/singleton/{type} returns the active document."""
    await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.005", "home_safe": "0.010"}},
    )

    resp = await singleton_client.get("/api/documents/singleton/storage_rates")
    assert resp.status_code == 200
    data = resp.json()
    assert data["singleton_status"] == "active"
    assert data["doc_type"] == "storage_rates"


async def test_singleton_publish_archives_previous(singleton_client):
    """Publishing v2 of a singleton archives v1."""
    r1 = await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.005", "home_safe": "0.010"}, "version_message": "v1"},
    )
    v1_id = r1.json()["id"]

    await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.004", "home_safe": "0.009"}, "version_message": "v2"},
    )

    v1_resp = await singleton_client.get(f"/api/documents/{v1_id}")
    assert v1_resp.status_code == 200
    assert v1_resp.json()["singleton_status"] == "archived"

    active_resp = await singleton_client.get("/api/documents/singleton/storage_rates")
    assert active_resp.status_code == 200
    assert active_resp.json()["body"]["bank_vault"] == "0.004"


async def test_singleton_publish_requires_one_active(singleton_client):
    """After publishing v2, only one document has singleton_status='active'."""
    await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.005", "home_safe": "0.010"}},
    )
    await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.004", "home_safe": "0.009"}},
    )
    await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.003", "home_safe": "0.008"}},
    )

    resp = await singleton_client.get("/api/documents?type=storage_rates")
    docs = resp.json()["documents"]
    active = [d for d in docs if d["singleton_status"] == "active"]
    assert len(active) == 1


async def test_singleton_history_ordered(singleton_client):
    """GET /history returns archived docs newest-first."""
    for rate in ["0.005", "0.004", "0.003"]:
        await singleton_client.post(
            "/api/documents/singleton/storage_rates",
            json={"body": {"bank_vault": rate, "home_safe": "0.010"}},
        )

    resp = await singleton_client.get("/api/documents/singleton/storage_rates/history")
    assert resp.status_code == 200
    history = resp.json()["history"]
    assert len(history) == 2
    assert all(h["singleton_status"] == "archived" for h in history)
    if history[0]["published_at"] and history[1]["published_at"]:
        assert history[0]["published_at"] >= history[1]["published_at"]


async def test_non_singleton_publish_unaffected(singleton_client):
    """Publishing a regular document does not touch singleton_status."""
    r1 = await singleton_client.post(
        "/api/documents/singleton/storage_rates",
        json={"body": {"bank_vault": "0.005", "home_safe": "0.010"}},
    )
    v1_id = r1.json()["id"]

    pub_resp = await singleton_client.post(f"/api/documents/{v1_id}/publish")
    assert pub_resp.status_code == 200
    assert pub_resp.json()["singleton_status"] == "active"


async def test_publish_singleton_endpoint_unknown_type(singleton_client):
    """POST /api/documents/singleton/{unknown_type} returns 422."""
    resp = await singleton_client.post(
        "/api/documents/singleton/unknown_block",
        json={"body": {}},
    )
    assert resp.status_code == 422


async def test_publish_singleton_endpoint_non_singleton_type(singleton_client):
    """POST /api/documents/singleton/{non_singleton_type} returns 422."""
    resp = await singleton_client.post(
        "/api/documents/singleton/jewelry_item",
        json={"body": {"name": "Ring"}},
    )
    assert resp.status_code == 422


async def test_singleton_webhook_payload_includes_flag(singleton_cms):
    """Webhook payload for singleton publish includes 'singleton': True."""
    import json
    from datetime import UTC, datetime

    import respx
    from nanoid import generate
    from starlette_cms.tables import CMSWebhook

    webhook_id = generate(size=21)
    await CMSWebhook.insert(
        CMSWebhook(
            id=webhook_id,
            url="http://testserver-webhook/hook",
            events=json.dumps(["document.published"]),
            created_at=datetime.now(UTC),
            active=True,
        )
    ).run()

    with respx.mock:
        mock_route = respx.post("http://testserver-webhook/hook").mock(
            return_value=httpx.Response(200)
        )

        app = Starlette(routes=[Mount("/", app=singleton_cms.app)])
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as c:
            resp = await c.post(
                "/api/documents/singleton/storage_rates",
                json={"body": {"bank_vault": "0.005", "home_safe": "0.010"}},
            )
            assert resp.status_code == 201

            import asyncio

            await asyncio.sleep(0.05)

        assert mock_route.called
        payload = json.loads(mock_route.calls[0].request.content)
        assert payload.get("singleton") is True


async def test_cms_documents_get_singleton_accessor(singleton_cms):
    """cms.documents.get_singleton() Python accessor works."""
    import pytest
    from starlette_cms.exceptions import DocumentNotFound

    with pytest.raises(DocumentNotFound):
        await singleton_cms.documents.get_singleton("storage_rates")

    import json
    from datetime import UTC, datetime

    from nanoid import generate
    from starlette_cms.tables import CMSDocument

    doc_id = generate(size=21)
    now = datetime.now(UTC)
    await CMSDocument.insert(
        CMSDocument(
            id=doc_id,
            doc_type="storage_rates",
            slug="",
            body=json.dumps({"bank_vault": "0.005", "home_safe": "0.010"}),
            meta="{}",
            created_at=now,
            updated_at=now,
            published=True,
            published_at=now,
            singleton_status="active",
        )
    ).run()

    result = await singleton_cms.documents.get_singleton("storage_rates")
    assert result["doc_type"] == "storage_rates"
    assert result["singleton_status"] == "active"


# ---------------------------------------------------------------------------
# DocumentRef fixtures and tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ref_client() -> AsyncGenerator[tuple[httpx.AsyncClient, CMS], None]:
    """
    CMS with two document types:
    - ``jewelry_item``: the referenced type
    - ``eval_entry``: has a DocumentRef(block_type="jewelry_item", on_delete="block")
                      and a nullify_ref DocumentRef(block_type="jewelry_item", on_delete="nullify")
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(database_url=f"sqlite:///{db_path}", auth="none", read_auth=False)

        @instance.document("jewelry_item")
        class JewelryItem:
            name: str = TextField(required=True)

        @instance.document("eval_entry")
        class EvalEntry:
            title: str = TextField(required=True)
            submission_ref: str = DocumentRef(block_type="jewelry_item", on_delete="block")
            rule_config_ref: str = DocumentRef(block_type="jewelry_item", on_delete="nullify")

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


async def test_create_document_with_valid_ref(ref_client):
    """Creating a document with a valid DocumentRef succeeds."""
    client, _cms = ref_client

    # Create the referenced document
    item_resp = await client.post(
        "/api/documents",
        json={"doc_type": "jewelry_item", "body": {"name": "Ruby Ring"}},
    )
    assert item_resp.status_code == 201
    item_id = item_resp.json()["id"]

    # Create an eval_entry referencing it
    eval_resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 1", "submission_ref": item_id},
        },
    )
    assert eval_resp.status_code == 201
    assert eval_resp.json()["body"]["submission_ref"] == item_id


async def test_create_document_invalid_ref_id(ref_client):
    """Creating a document with a non-existent ref ID returns 422."""
    client, _cms = ref_client

    resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 2", "submission_ref": "nonexistent-doc-id"},
        },
    )
    assert resp.status_code == 422
    assert "not found" in resp.json()["error"]


async def test_create_document_wrong_block_type_ref(ref_client):
    """Creating a document with a ref pointing at wrong block_type returns 422."""
    client, _cms = ref_client

    # Create an eval_entry (wrong type — ref should be jewelry_item)
    wrong_resp = await client.post(
        "/api/documents",
        json={"doc_type": "eval_entry", "body": {"title": "Eval 3"}},
    )
    wrong_id = wrong_resp.json()["id"]

    # Try to use it as a jewelry_item ref
    resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 4", "submission_ref": wrong_id},
        },
    )
    assert resp.status_code == 422
    assert "expected block_type" in resp.json()["error"]


async def test_patch_document_validates_new_ref(ref_client):
    """PATCH with a new DocumentRef value validates the new ref."""
    client, _cms = ref_client

    # Create an eval_entry without a ref
    eval_resp = await client.post(
        "/api/documents",
        json={"doc_type": "eval_entry", "body": {"title": "Eval 5"}},
    )
    eval_id = eval_resp.json()["id"]

    # Patch with a non-existent ref
    patch_resp = await client.patch(
        f"/api/documents/{eval_id}",
        json={"body": {"submission_ref": "bad-ref-id"}},
    )
    assert patch_resp.status_code == 422
    assert "not found" in patch_resp.json()["error"]


async def test_delete_blocked_by_ref(ref_client):
    """Deleting a document referenced by on_delete='block' returns 409."""
    client, _cms = ref_client

    item_resp = await client.post(
        "/api/documents",
        json={"doc_type": "jewelry_item", "body": {"name": "Diamond Ring"}},
    )
    item_id = item_resp.json()["id"]

    await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 6", "submission_ref": item_id},
        },
    )

    del_resp = await client.delete(f"/api/documents/{item_id}")
    assert del_resp.status_code == 409
    assert "Cannot delete" in del_resp.json()["error"]


async def test_delete_nullifies_ref(ref_client):
    """Deleting a document referenced by on_delete='nullify' sets the ref to None."""
    client, _cms = ref_client

    item_resp = await client.post(
        "/api/documents",
        json={"doc_type": "jewelry_item", "body": {"name": "Pearl Necklace"}},
    )
    item_id = item_resp.json()["id"]

    eval_resp = await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 7", "rule_config_ref": item_id},
        },
    )
    eval_id = eval_resp.json()["id"]

    # Delete the referenced document — should succeed (on_delete=nullify)
    del_resp = await client.delete(f"/api/documents/{item_id}")
    assert del_resp.status_code == 204

    # The eval_entry's rule_config_ref should now be None
    get_resp = await client.get(f"/api/documents/{eval_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["body"]["rule_config_ref"] is None


async def test_resolve_refs_in_list(ref_client):
    """GET /api/documents?resolve_refs=submission_ref returns __resolved keys."""
    client, _cms = ref_client

    item_resp = await client.post(
        "/api/documents",
        json={"doc_type": "jewelry_item", "body": {"name": "Sapphire Bracelet"}},
    )
    item_id = item_resp.json()["id"]

    await client.post(
        "/api/documents",
        json={
            "doc_type": "eval_entry",
            "body": {"title": "Eval 8", "submission_ref": item_id},
        },
    )

    resp = await client.get("/api/documents?type=eval_entry&resolve_refs=submission_ref")
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert len(docs) >= 1
    doc = next(d for d in docs if d["body"].get("submission_ref") == item_id)
    resolved = doc["body"].get("submission_ref__resolved")
    assert resolved is not None
    assert resolved["id"] == item_id
    assert resolved["body"]["name"] == "Sapphire Bracelet"


async def test_resolve_refs_no_n_plus_one(ref_client):
    """resolve_refs performs a single IN query per field — O(1) not O(N)."""
    client, _cms = ref_client

    # Create multiple jewelry items and eval entries referencing them
    item_ids = []
    for i in range(3):
        r = await client.post(
            "/api/documents",
            json={"doc_type": "jewelry_item", "body": {"name": f"Item {i}"}},
        )
        item_ids.append(r.json()["id"])

    for i, item_id in enumerate(item_ids):
        await client.post(
            "/api/documents",
            json={
                "doc_type": "eval_entry",
                "body": {"title": f"Eval {i}", "submission_ref": item_id},
            },
        )

    # The response should contain resolved refs for all entries — correctness check
    resp = await client.get("/api/documents?type=eval_entry&resolve_refs=submission_ref")
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    resolved_docs = [d for d in docs if d["body"].get("submission_ref__resolved")]
    assert len(resolved_docs) == 3


# ---------------------------------------------------------------------------
# Filter by body field (STORY-005)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def filter_cms():
    """CMS with a 'scenario' document type for filter tests; seeds a few rows."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        instance = CMS(
            database_url=f"sqlite:///{db_path}",
            auth="none",
            read_auth=False,
        )

        @instance.document("scenario")
        class Scenario:
            title: str = TextField(required=True)

        async with instance.lifespan_context(None):
            yield instance
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest_asyncio.fixture
async def filter_client(filter_cms):
    """httpx.AsyncClient for filter_cms."""
    app = Starlette(routes=[Mount("/", app=filter_cms.app)])
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c, filter_cms


async def _seed_scenario(
    cms_instance, title: str, active: bool, category: str, score: float | None = None
) -> str:
    """Insert a scenario row directly, bypassing API validation."""
    from nanoid import generate
    from starlette_cms.tables import CMSDocument

    doc_id = generate(size=21)
    body: dict = {"title": title, "active": active, "category": category}
    if score is not None:
        body["score"] = score
    now = datetime.now(UTC)
    await CMSDocument.insert(
        CMSDocument(
            id=doc_id,
            doc_type="scenario",
            slug=title.lower().replace(" ", "-"),
            body=json.dumps(body),
            meta="{}",
            created_at=now,
            updated_at=now,
            published=False,
            published_at=None,
        )
    ).run()
    return doc_id


async def test_filter_by_body_field_bool(filter_client):
    """?filters={"active":true} returns only active docs."""
    client, cms_instance = filter_client
    await _seed_scenario(cms_instance, "Active Scenario", active=True, category="jewelry")
    await _seed_scenario(cms_instance, "Inactive Scenario", active=False, category="jewelry")

    resp = await client.get('/api/documents?type=scenario&filters={"active":true}')
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert all(d["body"]["active"] is True for d in data["documents"])
    assert data["filters_applied"] == {"active": True}


async def test_filter_by_body_field_string(filter_client):
    """?filter[category]=jewelry returns only jewelry docs."""
    client, cms_instance = filter_client
    await _seed_scenario(cms_instance, "Jewelry Scenario", active=True, category="jewelry")
    await _seed_scenario(cms_instance, "Watch Scenario", active=True, category="watch")

    resp = await client.get("/api/documents?type=scenario&filter[category]=jewelry")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert all(d["body"]["category"] == "jewelry" for d in data["documents"])


async def test_filter_no_match_returns_empty(filter_client):
    """?filters={"active":false} on all-active docs returns empty list."""
    client, cms_instance = filter_client
    await _seed_scenario(cms_instance, "S1", active=True, category="ring")
    await _seed_scenario(cms_instance, "S2", active=True, category="ring")

    resp = await client.get('/api/documents?type=scenario&filters={"active":false}')
    assert resp.status_code == 200
    data = resp.json()
    assert data["documents"] == []
    assert data["total"] == 0


async def test_filter_combined(filter_client):
    """Multiple filters AND correctly — only docs matching all filters are returned."""
    client, cms_instance = filter_client
    await _seed_scenario(cms_instance, "Match", active=True, category="jewelry")
    await _seed_scenario(cms_instance, "Wrong Cat", active=True, category="watch")
    await _seed_scenario(cms_instance, "Wrong Active", active=False, category="jewelry")

    resp = await client.get(
        "/api/documents?type=scenario&filter[active]=true&filter[category]=jewelry"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["body"]["category"] == "jewelry"
    assert data["documents"][0]["body"]["active"] is True


async def test_filter_invalid_json(filter_client):
    """Malformed filters= param returns 400."""
    client, _cms = filter_client
    resp = await client.get("/api/documents?filters={not-valid-json}")
    assert resp.status_code == 400
    assert "filters" in resp.json()["error"]


async def test_order_by_created_at_asc(filter_client):
    """order_by=created_at&order=asc returns oldest first."""
    client, cms_instance = filter_client
    id1 = await _seed_scenario(cms_instance, "First", active=True, category="a")
    id2 = await _seed_scenario(cms_instance, "Second", active=True, category="a")
    id3 = await _seed_scenario(cms_instance, "Third", active=True, category="a")

    resp = await client.get("/api/documents?type=scenario&order_by=created_at&order=asc")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()["documents"]]
    assert ids.index(id1) < ids.index(id2) < ids.index(id3)


async def test_order_by_updated_at_desc(filter_client):
    """order_by=updated_at&order=desc returns newest-updated first (default order)."""
    client, cms_instance = filter_client
    id1 = await _seed_scenario(cms_instance, "Old", active=True, category="a")
    id2 = await _seed_scenario(cms_instance, "New", active=True, category="a")

    resp = await client.get("/api/documents?type=scenario&order_by=updated_at&order=desc")
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()["documents"]]
    assert ids.index(id2) < ids.index(id1)


async def test_order_by_invalid_field_falls_back(filter_client):
    """Unknown order_by field silently falls back to created_at."""
    client, _cms = filter_client
    resp = await client.get("/api/documents?type=scenario&order_by=nonexistent_field")
    assert resp.status_code == 200


async def test_total_reflects_filtered_count(filter_client):
    """total in response matches filtered count, not raw count."""
    client, cms_instance = filter_client
    await _seed_scenario(cms_instance, "A1", active=True, category="gold")
    await _seed_scenario(cms_instance, "A2", active=True, category="gold")
    await _seed_scenario(cms_instance, "A3", active=False, category="gold")

    resp = await client.get('/api/documents?type=scenario&filters={"active":true}')
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["documents"]) == 2


async def test_cms_documents_list_python_api(filter_cms):
    """cms.documents.list() Python accessor with body filters."""
    await _seed_scenario(filter_cms, "P1", active=True, category="silver")
    await _seed_scenario(filter_cms, "P2", active=False, category="silver")
    await _seed_scenario(filter_cms, "P3", active=True, category="gold")

    results = await filter_cms.documents.list("scenario", filters={"active": True})
    assert len(results) == 2
    assert all(r["body"]["active"] is True for r in results)

    results = await filter_cms.documents.list(
        "scenario", filters={"active": True, "category": "silver"}
    )
    assert len(results) == 1
    assert results[0]["body"]["category"] == "silver"
