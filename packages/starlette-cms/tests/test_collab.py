"""
Tests for the WebSocket collaborative editing authority (Phase NS-2).

Uses Starlette's synchronous TestClient for WebSocket tests (it handles the
async ASGI app internally) and httpx.AsyncClient for the history HTTP endpoints.
"""

from __future__ import annotations

import json
import os
import tempfile

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from starlette_cms import CMS, TextField


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cms(auth: str = "none", api_key: str | None = None) -> tuple[CMS, str]:
    """Create a CMS with a temp SQLite DB and return (cms, db_path)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    instance = CMS(
        database_url=f"sqlite:///{tmp.name}",
        auth=auth,
        api_key=api_key,
        read_auth=False,
    )

    @instance.block("note")
    class NoteBlock:
        title: str = TextField(required=True)

    return instance, tmp.name


# ---------------------------------------------------------------------------
# Sync pytest fixtures (for TestClient / WebSocket tests)
# ---------------------------------------------------------------------------


@pytest.fixture()
def cms_with_doc():
    """
    Returns (TestClient, doc_id) for WebSocket testing.

    Uses Starlette's TestClient with lifespan="on" so the DB initialisation
    runs before any request.  A single 'note' document is pre-created.
    """
    cms, db_path = _make_cms()
    app = Starlette(routes=[Mount("/", app=cms.app)], lifespan=cms.lifespan)

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/documents",
                json={"doc_type": "note", "slug": "test-note", "body": {"title": "Hello"}},
            )
            assert resp.status_code == 201, f"Document creation failed: {resp.text}"
            doc_id = resp.json()["id"]
            yield client, doc_id
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.fixture()
def authed_cms_with_doc():
    """Like cms_with_doc but with apikey auth configured."""
    cms, db_path = _make_cms(auth="apikey", api_key="test-secret")
    app = Starlette(routes=[Mount("/", app=cms.app)], lifespan=cms.lifespan)

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/documents",
                json={"doc_type": "note", "slug": "auth-note", "body": {"title": "Authed"}},
                headers={"Authorization": "Bearer test-secret"},
            )
            assert resp.status_code == 201, f"Document creation failed: {resp.text}"
            doc_id = resp.json()["id"]
            yield client, doc_id, cms
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Async fixtures (for httpx history endpoint tests)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_cms_with_doc():
    """Async version: returns (httpx.AsyncClient, doc_id, cms) for history tests."""
    cms, db_path = _make_cms()
    app = Starlette(routes=[Mount("/", app=cms.app)])

    try:
        async with cms.lifespan_context(None):
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
            ) as aclient:
                resp = await aclient.post(
                    "/api/documents",
                    json={"doc_type": "note", "slug": "async-note", "body": {"title": "Async"}},
                )
                assert resp.status_code == 201
                doc_id = resp.json()["id"]
                yield aclient, doc_id, cms
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 1: Single client connect — receives init message
# ---------------------------------------------------------------------------


def test_ws_connect_receives_init(cms_with_doc):
    client, doc_id = cms_with_doc
    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        data = ws.receive_json()
        assert data["type"] == "init"
        assert "doc" in data
        assert data["version"] == 0


# ---------------------------------------------------------------------------
# Test 2: Single client sends steps — receives confirmation
# ---------------------------------------------------------------------------


def test_ws_send_steps_accepted(cms_with_doc):
    client, doc_id = cms_with_doc
    step = {"stepType": "replace", "from": 0, "to": 1, "slice": {"content": []}}
    updated_doc = {"title": "Updated"}

    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        ws.receive_json()  # init

        ws.send_json(
            {
                "type": "steps",
                "steps": [step],
                "clientID": "client-a",
                "version": 0,
                "doc": updated_doc,
            }
        )
        msg = ws.receive_json()

    assert msg["type"] == "steps"
    assert msg["version"] == 1
    assert len(msg["steps"]) == 1
    assert msg["clientIDs"] == ["client-a"]


# ---------------------------------------------------------------------------
# Test 3: Draft updated in DB after accepted steps
# ---------------------------------------------------------------------------


async def test_draft_updated_in_db(async_cms_with_doc):
    aclient, doc_id, cms = async_cms_with_doc

    # Seed the authority via a WebSocket-like direct call
    from starlette_cms.tables import CMSDocument

    authority = await cms.collab_manager.get_or_create_authority(doc_id)
    updated_doc = {"title": "After step"}
    base_version = authority._version
    async with authority._lock:
        result = authority.apply_steps(
            [{"stepType": "replace", "from": 0, "to": 1, "slice": {}}],
            "test-client",
            0,
            updated_doc,
        )
    assert result.accepted

    await authority._persist_steps(
        [{"stepType": "replace", "from": 0, "to": 1, "slice": {}}],
        "test-client",
        base_version,
    )

    rows = (
        await CMSDocument.select(CMSDocument.draft_body, CMSDocument.draft_version)
        .where(CMSDocument.id == doc_id)
        .run()
    )
    assert rows[0]["draft_version"] == 1
    stored = rows[0]["draft_body"]
    parsed = json.loads(stored) if isinstance(stored, str) else stored
    assert parsed == updated_doc


# ---------------------------------------------------------------------------
# Test 4: Steps persisted in CMSStep after accepted steps
# ---------------------------------------------------------------------------


async def test_steps_persisted_in_db(async_cms_with_doc):
    aclient, doc_id, cms = async_cms_with_doc
    from starlette_cms.tables import CMSStep

    authority = await cms.collab_manager.get_or_create_authority(doc_id)
    step = {"stepType": "replace", "from": 0, "to": 1, "slice": {}}
    base_version = authority._version

    async with authority._lock:
        result = authority.apply_steps([step], "client-persist", 0, {"title": "p"})
    assert result.accepted

    await authority._persist_steps([step], "client-persist", base_version)

    step_rows = await CMSStep.select().where(CMSStep.document_id == doc_id).run()
    assert len(step_rows) >= 1
    assert step_rows[0]["client_id"] == "client-persist"
    assert step_rows[0]["version"] == 1


# ---------------------------------------------------------------------------
# Test 5: Version mismatch → reject
# ---------------------------------------------------------------------------


def test_ws_version_mismatch_rejected(cms_with_doc):
    client, doc_id = cms_with_doc
    step = {"stepType": "replace", "from": 0, "to": 1, "slice": {}}

    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        ws.receive_json()  # init

        ws.send_json(
            {
                "type": "steps",
                "steps": [step],
                "clientID": "late-client",
                "version": 99,  # wrong version
                "doc": {"title": "x"},
            }
        )
        msg = ws.receive_json()

    assert msg["type"] == "reject"
    assert msg["version"] == 0


# ---------------------------------------------------------------------------
# Test 6: Two clients — client B receives broadcast from client A
# ---------------------------------------------------------------------------


def test_ws_two_client_broadcast(cms_with_doc):
    client, doc_id = cms_with_doc
    step = {"stepType": "replace", "from": 0, "to": 1, "slice": {}}

    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws_a:
        ws_a.receive_json()  # init for A

        with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws_b:
            ws_b.receive_json()  # init for B

            ws_a.send_json(
                {
                    "type": "steps",
                    "steps": [step],
                    "clientID": "client-a",
                    "version": 0,
                    "doc": {"title": "from A"},
                }
            )

            # Client A should receive the broadcast (confirmation)
            msg_a = ws_a.receive_json()
            assert msg_a["type"] == "steps"
            assert msg_a["version"] == 1

            # Client B should also receive the broadcast
            msg_b = ws_b.receive_json()
            assert msg_b["type"] == "steps"
            assert msg_b["version"] == 1
            assert msg_b["clientIDs"] == ["client-a"]


# ---------------------------------------------------------------------------
# Test 7: Ping → pong
# ---------------------------------------------------------------------------


def test_ws_ping_pong(cms_with_doc):
    client, doc_id = cms_with_doc
    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        ws.receive_json()  # init
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
    assert msg["type"] == "pong"


# ---------------------------------------------------------------------------
# Test 8: Document not found → error + close
# ---------------------------------------------------------------------------


def test_ws_document_not_found(cms_with_doc):
    client, _ = cms_with_doc
    with client.websocket_connect("/api/documents/nonexistent-id/collab") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "not found" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Test 9: Auth=none — connect without any auth → succeeds
# ---------------------------------------------------------------------------


def test_ws_auth_none_allows_unauthenticated(cms_with_doc):
    client, doc_id = cms_with_doc
    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        data = ws.receive_json()
    assert data["type"] == "init"


# ---------------------------------------------------------------------------
# Test 10: Auth=apikey — wrong key → close 4401
# ---------------------------------------------------------------------------


def test_ws_auth_apikey_wrong_key_rejected(authed_cms_with_doc):
    client, doc_id, _ = authed_cms_with_doc
    # Starlette TestClient raises WebSocketDisconnect on close-before-accept
    from starlette.testclient import WebSocketTestSession
    from starlette.websockets import WebSocketDisconnect

    try:
        with client.websocket_connect(
            f"/api/documents/{doc_id}/collab?api_key=wrong-key"
        ) as ws:
            ws.receive_json()
        # If we get here, auth was not enforced
        pytest.fail("Expected rejection but connection was accepted")
    except Exception:
        pass  # Connection was refused / closed — expected


# ---------------------------------------------------------------------------
# Test 11: Auth=apikey — correct key → init received
# ---------------------------------------------------------------------------


def test_ws_auth_apikey_correct_key_accepted(authed_cms_with_doc):
    client, doc_id, _ = authed_cms_with_doc
    with client.websocket_connect(
        f"/api/documents/{doc_id}/collab?api_key=test-secret"
    ) as ws:
        data = ws.receive_json()
    assert data["type"] == "init"


# ---------------------------------------------------------------------------
# Test 12: History endpoint returns checkpoints after steps
# ---------------------------------------------------------------------------


async def test_history_endpoint_returns_checkpoints(async_cms_with_doc):
    aclient, doc_id, cms = async_cms_with_doc
    from starlette_cms.tables import CMSStep
    from datetime import UTC, datetime

    # Insert a couple of step rows directly
    now = datetime.now(UTC)
    await CMSStep.insert(
        CMSStep(
            document_id=doc_id,
            client_id="hist-client",
            version=1,
            step_data=json.dumps({"stepType": "replace"}),
            created_at=now,
        ),
        CMSStep(
            document_id=doc_id,
            client_id="hist-client",
            version=2,
            step_data=json.dumps({"stepType": "replace"}),
            created_at=now,
        ),
    ).run()

    resp = await aclient.get(f"/api/documents/{doc_id}/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == doc_id
    assert "checkpoints" in data
    assert "current_version" in data
    # Should have at least one checkpoint covering our two steps
    assert len(data["checkpoints"]) >= 1
    cp = data["checkpoints"][0]
    assert "version_from" in cp
    assert "version_to" in cp
    assert "step_count" in cp


# ---------------------------------------------------------------------------
# Test 13: History at version returns baseline + steps
# ---------------------------------------------------------------------------


async def test_history_at_version_returns_steps(async_cms_with_doc):
    aclient, doc_id, cms = async_cms_with_doc
    from starlette_cms.tables import CMSStep
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    step1 = {"stepType": "replace", "from": 0, "to": 1}
    step2 = {"stepType": "addMark", "mark": {"type": "bold"}}
    await CMSStep.insert(
        CMSStep(
            document_id=doc_id,
            client_id="ver-client",
            version=1,
            step_data=json.dumps(step1),
            created_at=now,
        ),
        CMSStep(
            document_id=doc_id,
            client_id="ver-client",
            version=2,
            step_data=json.dumps(step2),
            created_at=now,
        ),
    ).run()

    resp = await aclient.get(f"/api/documents/{doc_id}/history/1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 1
    assert data["step_count"] == 1
    assert "baseline_body" in data
    assert len(data["steps"]) == 1
    assert data["steps"][0]["stepType"] == "replace"

    # At version 2 we should get both steps
    resp2 = await aclient.get(f"/api/documents/{doc_id}/history/2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["step_count"] == 2
    assert len(data2["steps"]) == 2
