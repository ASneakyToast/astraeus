"""
Tests for WebSocket peer-presence features (Phase CH-4B).

Covers: init peers array, peer_joined broadcast, peer_left on disconnect,
AI client_type propagation, and editing broadcast.

Follows the exact same fixture/TestClient patterns as test_collab.py.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from starlette_cms import CMS, TextField


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_cms() -> tuple[CMS, str]:
    """Create a CMS with a temp SQLite DB and return (cms, db_path)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()

    instance = CMS(
        database_url=f"sqlite:///{tmp.name}",
        auth="none",
        read_auth=False,
    )

    @instance.block("note")
    class NoteBlock:
        title: str = TextField(required=True)

    return instance, tmp.name


@pytest.fixture()
def cms_with_doc():
    """Return (TestClient, doc_id) for peer-presence WebSocket tests."""
    cms, db_path = _make_cms()
    app = Starlette(routes=[Mount("/", app=cms.app)], lifespan=cms.lifespan)

    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post(
                "/api/documents",
                json={"doc_type": "note", "slug": "peer-note", "body": {"title": "Hello"}},
            )
            assert resp.status_code == 201, f"Document creation failed: {resp.text}"
            doc_id = resp.json()["id"]
            yield client, doc_id
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Test 1: init message contains a "peers" array
# ---------------------------------------------------------------------------


def test_init_message_has_peers_array(cms_with_doc):
    client, doc_id = cms_with_doc
    with client.websocket_connect(f"/api/documents/{doc_id}/collab") as ws:
        data = ws.receive_json()
    assert data["type"] == "init"
    assert "peers" in data
    assert isinstance(data["peers"], list)


# ---------------------------------------------------------------------------
# Test 2: peer_joined broadcast when B sends a presence message
# ---------------------------------------------------------------------------


def test_peer_joined_broadcast(cms_with_doc):
    client, doc_id = cms_with_doc
    url = f"/api/documents/{doc_id}/collab"

    with client.websocket_connect(url) as ws_a:
        ws_a.receive_json()  # consume init for A

        with client.websocket_connect(url) as ws_b:
            ws_b.receive_json()  # consume init for B
            ws_b.send_json(
                {"type": "presence", "display": "Alice", "client_type": "human"}
            )

            # A should receive a peer_joined event
            msg = ws_a.receive_json()

    assert msg["type"] == "peer_joined"
    assert "peer" in msg
    assert msg["peer"]["display"] == "Alice"
    assert msg["peer"]["type"] == "human"


# ---------------------------------------------------------------------------
# Test 3: peer_left broadcast when B disconnects
# ---------------------------------------------------------------------------


def test_peer_left_on_disconnect(cms_with_doc):
    client, doc_id = cms_with_doc
    url = f"/api/documents/{doc_id}/collab"

    with client.websocket_connect(url) as ws_a:
        ws_a.receive_json()  # consume init for A

        with client.websocket_connect(url) as ws_b:
            ws_b.receive_json()  # consume init for B
            # B announces itself so the server tracks it
            ws_b.send_json(
                {"type": "presence", "display": "Bob", "client_type": "human"}
            )
            # A receives peer_joined — consume it
            ws_a.receive_json()
        # ws_b context exits → B disconnects → server broadcasts peer_left to A

        msg = ws_a.receive_json()

    assert msg["type"] == "peer_left"
    assert "client_id" in msg


# ---------------------------------------------------------------------------
# Test 4: AI client_type is propagated in the peer_joined message
# ---------------------------------------------------------------------------


def test_ai_peer_type_in_peer_joined(cms_with_doc):
    client, doc_id = cms_with_doc
    url = f"/api/documents/{doc_id}/collab"

    with client.websocket_connect(url) as ws_a:
        ws_a.receive_json()  # consume init for A

        with client.websocket_connect(url) as ws_b:
            ws_b.receive_json()  # consume init for B
            ws_b.send_json(
                {"type": "presence", "display": "GPT-Collab", "client_type": "ai"}
            )

            msg = ws_a.receive_json()

    assert msg["type"] == "peer_joined"
    peer = msg["peer"]
    # The server stores and transmits the type field
    assert peer.get("type") == "ai" or peer.get("client_type") == "ai"
    assert peer["display"] == "GPT-Collab"


# ---------------------------------------------------------------------------
# Test 5: "editing" message is broadcast to other connected clients
# ---------------------------------------------------------------------------


def test_editing_message_broadcast(cms_with_doc):
    client, doc_id = cms_with_doc
    url = f"/api/documents/{doc_id}/collab"
    step = {"stepType": "replace", "from": 0, "to": 1, "slice": {"content": []}}

    with client.websocket_connect(url) as ws_a:
        ws_a.receive_json()  # consume init for A

        with client.websocket_connect(url) as ws_b:
            ws_b.receive_json()  # consume init for B

            # A announces presence first (so A enters main loop quickly)
            ws_a.send_json(
                {"type": "presence", "display": "Editor-A", "client_type": "human"}
            )
            # B receives peer_joined for A
            joined = ws_b.receive_json()
            assert joined["type"] == "peer_joined"

            # Now B sends an "editing" message; A should receive it
            ws_b.send_json({"type": "editing"})
            msg = ws_a.receive_json()

    assert msg["type"] == "editing"
    assert "client_id" in msg
