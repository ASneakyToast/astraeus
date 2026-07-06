"""
Collaborative editing authority for starlette-cms.

Implements the server side of the prosemirror-collab protocol.
One CollabAuthority instance per document manages connected clients.

Usage::

    manager = CollabManager()
    authority = await manager.get_or_create_authority(document_id)
    async with authority._lock:
        result = authority.apply_steps(steps, client_id, client_version, updated_doc)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.websockets import WebSocket


@dataclass
class CollabResult:
    """Result of applying a batch of ProseMirror steps to the authority."""

    accepted: bool
    version: int
    steps: list[dict] = field(default_factory=list)
    client_ids: list[str] = field(default_factory=list)


class CollabAuthority:
    """
    Server-side authority for a single document's collaborative editing state.

    Holds the current authoritative document state and version counter.
    ``apply_steps`` must be called while the caller holds ``self._lock``.

    :param document_id: The CMS document ID this authority manages.
    :param draft_body: Current authoritative document state (dict).
    :param version: Current version number (incremented per accepted step).
    """

    def __init__(self, document_id: str, draft_body: dict, version: int) -> None:
        self.document_id = document_id
        self._doc = draft_body
        self._version = version
        self._lock = asyncio.Lock()
        self._last_activity = time.monotonic()

    def apply_steps(
        self,
        steps: list[dict],
        client_id: str,
        client_version: int,
        updated_doc: dict,
    ) -> CollabResult:
        """
        Attempt to apply a batch of ProseMirror steps from a client.

        Must be called while holding ``self._lock``.

        :param steps: List of ProseMirror step dicts (each must have ``stepType``).
        :param client_id: Opaque client identifier string.
        :param client_version: The version the client claims to be based on.
        :param updated_doc: The client's document state after applying steps.
        :returns: ``CollabResult`` with ``accepted=True`` on success.
        """
        # Version must match exactly
        if client_version != self._version:
            return CollabResult(accepted=False, version=self._version)

        # Structural validation: each step must be a dict with a non-empty stepType
        for step in steps:
            if not isinstance(step, dict):
                return CollabResult(accepted=False, version=self._version)
            step_type = step.get("stepType")
            if not isinstance(step_type, str) or not step_type:
                return CollabResult(accepted=False, version=self._version)

        # Accept: advance version and update authoritative doc state
        self._version += len(steps)
        self._doc = updated_doc
        self._last_activity = time.monotonic()

        return CollabResult(
            accepted=True,
            version=self._version,
            steps=steps,
            client_ids=[client_id],
        )

    async def _persist_steps(self, steps: list[dict], client_id: str, base_version: int) -> None:
        """Persist accepted steps to the DB and update CMSDocument draft fields.

        :param steps: The accepted step dicts.
        :param client_id: The accepting client's ID.
        :param base_version: The version number *before* these steps were applied
            (i.e. ``self._version - len(steps)`` at the time of the call).
        """
        from starlette_cms.tables import CMSDocument, CMSStep

        now = datetime.now(UTC)
        step_rows = [
            CMSStep(
                document_id=self.document_id,
                client_id=client_id,
                version=base_version + i + 1,
                step_data=json.dumps(step),
                created_at=now,
            )
            for i, step in enumerate(steps)
        ]
        await CMSStep.insert(*step_rows).run()

        await CMSDocument.update(
            {
                CMSDocument.draft_body: json.dumps(self._doc),
                CMSDocument.draft_version: self._version,
            }
        ).where(CMSDocument.id == self.document_id).run()


class CollabManager:
    """
    Manages one :class:`CollabAuthority` per document and the set of active
    WebSocket connections.

    A single ``CollabManager`` instance lives on the :class:`~starlette_cms.app.CMS`
    object and is shared across all requests.
    """

    def __init__(self) -> None:
        self._authorities: dict[str, CollabAuthority] = {}
        self._connections: dict[str, set[WebSocket]] = {}
        self._peer_info: dict[str, dict] = {}
        self._ws_to_client_id: dict = {}  # WebSocket → server-assigned client_id
        self._manager_lock = asyncio.Lock()

    async def get_or_create_authority(self, document_id: str) -> CollabAuthority:
        """Return the existing authority for *document_id*, or load one from DB.

        :raises KeyError: if no CMSDocument with *document_id* exists.
        """
        if document_id in self._authorities:
            return self._authorities[document_id]

        async with self._manager_lock:
            # Re-check inside the lock
            if document_id in self._authorities:
                return self._authorities[document_id]

            from starlette_cms.tables import CMSDocument

            rows = (
                await CMSDocument.select(
                    CMSDocument.id,
                    CMSDocument.body,
                    CMSDocument.draft_body,
                    CMSDocument.draft_version,
                )
                .where(CMSDocument.id == document_id)
                .limit(1)
                .run()
            )
            if not rows:
                raise KeyError(document_id)

            row = rows[0]
            raw_draft = row.get("draft_body")
            if raw_draft is not None:
                draft_body = json.loads(raw_draft) if isinstance(raw_draft, str) else raw_draft
            else:
                raw_body = row.get("body", "{}")
                draft_body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

            version = row.get("draft_version") or 0
            authority = CollabAuthority(document_id, draft_body, version)
            self._authorities[document_id] = authority
            return authority

    async def add_connection(self, document_id: str, ws: WebSocket) -> None:
        """Register a WebSocket connection for *document_id*."""
        async with self._manager_lock:
            if document_id not in self._connections:
                self._connections[document_id] = set()
            self._connections[document_id].add(ws)

    async def remove_connection(self, document_id: str, ws: WebSocket) -> None:
        """Unregister a WebSocket connection. Schedules GC if no connections remain."""
        async with self._manager_lock:
            conns = self._connections.get(document_id, set())
            conns.discard(ws)
            if not conns:
                self._connections.pop(document_id, None)

    async def broadcast(
        self,
        document_id: str,
        message: dict,
        exclude: WebSocket | None = None,
    ) -> None:
        """Send *message* as JSON to all connections for *document_id*.

        :param exclude: If supplied, this WebSocket is skipped.
        """
        conns = set(self._connections.get(document_id, set()))
        for ws in conns:
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass  # stale connection — will be cleaned up on disconnect

    def _bind_client(self, ws: WebSocket, client_id: str) -> None:
        """Associate a WebSocket connection with its server-assigned client_id.

        Must be called after :meth:`add_connection` so that
        :meth:`get_peers_for_doc` can map live connections back to peer info.

        :param ws: The active WebSocket connection.
        :param client_id: The server-generated UUID for this connection.
        """
        self._ws_to_client_id[ws] = client_id

    def register_peer(self, client_id: str, display: str, client_type: str) -> None:
        """Store presence information for a connected peer.

        :param client_id: Server-assigned UUID for the connection.
        :param display: Human-readable display name sent by the client.
        :param client_type: ``"human"`` or ``"ai"``.
        """
        self._peer_info[client_id] = {
            "client_id": client_id,
            "display": display,
            "type": client_type,
        }

    def unregister_peer(self, client_id: str) -> None:
        """Remove a peer's presence information and clean up the reverse WS map.

        :param client_id: Server-assigned UUID for the connection.
        """
        self._peer_info.pop(client_id, None)
        stale = [ws for ws, cid in self._ws_to_client_id.items() if cid == client_id]
        for ws in stale:
            self._ws_to_client_id.pop(ws, None)

    def get_peers_for_doc(self, doc_id: str) -> list[dict]:
        """Return peer-info dicts for all registered connections on *doc_id*.

        Uses ``self._connections[doc_id]`` to find active WebSockets, then
        maps each to a ``client_id`` via ``_ws_to_client_id``, and finally
        looks up the full peer dict in ``_peer_info``.

        :param doc_id: The CMS document ID.
        :returns: List of peer dicts (``client_id``, ``display``, ``type``).
        """
        conns = self._connections.get(doc_id, set())
        peers: list[dict] = []
        for ws in conns:
            client_id = self._ws_to_client_id.get(ws)
            if client_id and client_id in self._peer_info:
                peers.append(self._peer_info[client_id])
        return peers

    async def broadcast_peer_event(
        self,
        doc_id: str,
        message: dict,
        exclude: Any | None = None,
    ) -> None:
        """Broadcast a peer-presence event to all connections on *doc_id*.

        Mirrors :meth:`broadcast` but is dedicated to peer events so callers
        can pass a WebSocket (or any sentinel) to ``exclude``.

        :param doc_id: The CMS document ID.
        :param message: JSON-serialisable dict to send.
        :param exclude: If supplied, this WebSocket is skipped.
        """
        conns = set(self._connections.get(doc_id, set()))
        for ws in conns:
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                pass  # stale connection — will be cleaned up on disconnect

    async def gc_if_idle(self, document_id: str, delay: float = 300.0) -> None:
        """After *delay* seconds, evict the authority if no connections remain.

        Fire-and-forget: called from the finally block of the WebSocket handler.
        """

        async def _gc() -> None:
            await asyncio.sleep(delay)
            async with self._manager_lock:
                if document_id not in self._connections:
                    self._authorities.pop(document_id, None)

        asyncio.ensure_future(_gc())
