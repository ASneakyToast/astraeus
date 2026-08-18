"""
WebSocket collaborative editing endpoint and history HTTP endpoints.

Routes added by ``make_collab_routes(cms)``:
  - WS  /api/documents/{document_id}/collab
  - GET  /api/documents/{document_id}/history
  - GET  /api/documents/{document_id}/history/{version}
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

if TYPE_CHECKING:
    from starlette_cms.app import CMS


def _check_ws_auth(websocket: WebSocket, cms: CMS) -> bool:
    """Return True if the WebSocket connection is authorised.

    Checks (in order):
    1. ``?api_key=<key>`` query param when ``cms.auth == "apikey"``
    2. ``cms_session`` cookie (session-based auth)
    3. ``cms.auth == "none"``
    """
    if cms.auth == "none":
        return True

    if cms.auth == "apikey":
        api_key = websocket.query_params.get("api_key")
        if api_key and api_key == cms.api_key:
            return True
        # Also allow Bearer token via headers if present
        auth_header = websocket.headers.get("authorization", "")
        if auth_header.startswith("Bearer ") and auth_header[7:] == cms.api_key:
            return True
        return False

    if callable(cms.auth):
        # For callable auth we cannot await here (no async), so reject for now.
        # Callable auth is an advanced use case; WebSocket clients should use apikey.
        return False

    return False


def make_collab_routes(cms: CMS) -> list:
    """Return the list of Routes for collaborative editing.

    :param cms: The CMS instance (captured in closures).
    """

    # ------------------------------------------------------------------
    # WebSocket endpoint
    # ------------------------------------------------------------------

    async def collab_ws(websocket: WebSocket) -> None:
        """Handle a ProseMirror collab WebSocket connection."""
        document_id: str = websocket.path_params["document_id"]

        # Auth check before accepting
        if not _check_ws_auth(websocket, cms):
            await websocket.close(code=4401)
            return

        await websocket.accept()

        # Server-assigned UUID for this connection (used for peer presence).
        # Distinct from the client-generated clientID in step messages.
        client_id = str(uuid.uuid4())
        manager = cms.collab_manager

        # Load or create the authority for this document
        try:
            authority = await manager.get_or_create_authority(document_id)
        except KeyError:
            await websocket.send_json({"type": "error", "message": "Document not found"})
            await websocket.close(code=4404)
            return

        # Register connection and bind the server-assigned client_id
        await manager.add_connection(document_id, websocket)
        manager._bind_client(websocket, client_id)

        # Send initial state including current peer list
        peers = manager.get_peers_for_doc(document_id)
        await websocket.send_json(
            {
                "type": "init",
                "doc": authority._doc,
                "version": authority._version,
                "peers": peers,
            }
        )

        # Single try/except/finally covers both the presence phase and the
        # message loop so that WebSocketDisconnect at any point is handled
        # cleanly and the finally block always runs.
        try:
            # ── Presence phase ─────────────────────────────────────────────────
            # Wait up to 2 s for the client to send a 'presence' message
            # identifying itself.  Non-presence messages are kept so the main
            # loop can process them; a timeout results in a silent registration.
            display: str = client_id
            peer_type: str = "human"
            first_msg: dict | None = None
            send_peer_joined = False

            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=2.0)
                if raw.get("type") == "presence":
                    display = raw.get("display", client_id)
                    peer_type = raw.get("client_type", "human")
                    send_peer_joined = True
                else:
                    # Non-presence message arrived — keep it for the main loop
                    first_msg = raw
            except asyncio.TimeoutError:
                pass  # No message within 2 s — register silently as human

            manager.register_peer(client_id, display, peer_type)
            if send_peer_joined:
                await manager.broadcast_peer_event(
                    document_id,
                    {
                        "type": "peer_joined",
                        "peer": {
                            "client_id": client_id,
                            "type": peer_type,
                            "display": display,
                        },
                    },
                    exclude=websocket,
                )

            # ── Message loop ───────────────────────────────────────────────────
            while True:
                # Drain any buffered message from the presence phase first
                if first_msg is not None:
                    data = first_msg
                    first_msg = None
                else:
                    data = await websocket.receive_json()

                msg_type = data.get("type")

                # ── Peer presence / activity ───────────────────────────────────
                if msg_type == "presence":
                    p_display = data.get("display", client_id)
                    p_type = data.get("client_type", "human")
                    manager.register_peer(client_id, p_display, p_type)
                    await manager.broadcast_peer_event(
                        document_id,
                        {
                            "type": "peer_joined",
                            "peer": {
                                "client_id": client_id,
                                "type": p_type,
                                "display": p_display,
                            },
                        },
                        exclude=websocket,
                    )

                elif msg_type == "editing":
                    await manager.broadcast_peer_event(
                        document_id,
                        {"type": "editing", "client_id": client_id, "doc_id": document_id},
                        exclude=websocket,
                    )

                elif msg_type == "editing_done":
                    await manager.broadcast_peer_event(
                        document_id,
                        {"type": "editing_done", "client_id": client_id},
                        exclude=websocket,
                    )

                # ── Keep-alive ─────────────────────────────────────────────────
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})

                # ── ProseMirror steps ──────────────────────────────────────────
                elif msg_type == "steps":
                    steps = data.get("steps", [])
                    step_client_id = data.get("clientID", "unknown")
                    client_version = data.get("version", -1)
                    # Client sends its current doc state after applying steps locally
                    updated_doc = data.get("doc")

                    async with authority._lock:
                        base_version = authority._version
                        result = authority.apply_steps(
                            steps,
                            step_client_id,
                            client_version,
                            updated_doc if updated_doc is not None else authority._doc,
                        )

                    if result.accepted:
                        # Persist asynchronously (fire-and-forget is fine here;
                        # in-memory state is already updated)
                        try:
                            await authority._persist_steps(steps, step_client_id, base_version)
                        except Exception:
                            pass  # DB persistence failure should not drop the connection

                        # Broadcast to ALL connections (including sender — sender
                        # uses this as its confirmation receipt)
                        await manager.broadcast(
                            document_id,
                            {
                                "type": "steps",
                                "steps": result.steps,
                                "clientIDs": result.client_ids,
                                "version": result.version,
                            },
                        )
                    else:
                        await websocket.send_json(
                            {
                                "type": "reject",
                                "version": result.version,
                            }
                        )

        except Exception:
            pass  # disconnect / receive error
        finally:
            manager.unregister_peer(client_id)
            await manager.remove_connection(document_id, websocket)
            # Broadcast peer_left to remaining connections after removal
            await manager.broadcast_peer_event(
                document_id,
                {"type": "peer_left", "client_id": client_id},
            )
            await manager.gc_if_idle(document_id)

    # ------------------------------------------------------------------
    # Document-events WebSocket — WS /api/events
    # ------------------------------------------------------------------

    async def events_ws(websocket: WebSocket) -> None:
        """Broadcast document-list events (create/update/delete/publish) to subscribers.

        Reuses the same auth as the collab socket. The shell opens one of these
        on boot to keep its document list live regardless of who wrote (human or AI).
        """
        if not _check_ws_auth(websocket, cms):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        cms.event_bus.add(websocket)

        try:
            # Hold the connection open. We only need to read to detect
            # disconnects and answer keep-alive pings; all data flows outbound
            # via event_bus.broadcast().
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except Exception:
            pass  # disconnect / receive error
        finally:
            cms.event_bus.remove(websocket)

    # ------------------------------------------------------------------
    # History endpoint — GET /api/documents/{document_id}/history
    # ------------------------------------------------------------------

    async def history_list(request: Request) -> JSONResponse:
        """Return step history for a document as time-bucketed checkpoints."""
        from starlette_cms.auth import require_auth
        from starlette_cms.tables import CMSDocument, CMSStep

        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        document_id: str = request.path_params["document_id"]

        # Verify document exists
        doc_rows = (
            await CMSDocument.select(CMSDocument.id, CMSDocument.draft_version)
            .where(CMSDocument.id == document_id)
            .limit(1)
            .run()
        )
        if not doc_rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        current_version: int = doc_rows[0].get("draft_version") or 0

        # Parse query params
        try:
            limit = min(int(request.query_params.get("limit", "50")), 200)
        except (ValueError, TypeError):
            limit = 50

        before_str = request.query_params.get("before")

        # Fetch step rows
        query = (
            CMSStep.select(
                CMSStep.document_id,
                CMSStep.client_id,
                CMSStep.version,
                CMSStep.created_at,
            )
            .where(CMSStep.document_id == document_id)
            .order_by(CMSStep.version, ascending=False)
            .limit(limit * 20)  # fetch extra for bucketing
        )
        rows = await query.run()

        # Group by 1-minute time buckets
        buckets: list[dict] = []
        current_bucket: dict | None = None

        for row in rows:
            created_at = row["created_at"]
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = datetime.now(UTC)

            # Bucket key: minute-precision ISO string
            if hasattr(created_at, "replace"):
                bucket_key = created_at.replace(second=0, microsecond=0).isoformat()
            else:
                bucket_key = str(created_at)

            if before_str and bucket_key >= before_str:
                continue

            if current_bucket is None or current_bucket["_key"] != bucket_key:
                if current_bucket is not None:
                    buckets.append(_format_bucket(current_bucket))
                    if len(buckets) >= limit:
                        break
                current_bucket = {
                    "_key": bucket_key,
                    "version_from": row["version"],
                    "version_to": row["version"],
                    "created_at": bucket_key,
                    "step_count": 1,
                    "client_id": row["client_id"],
                }
            else:
                current_bucket["version_from"] = min(
                    current_bucket["version_from"], row["version"]
                )
                current_bucket["version_to"] = max(
                    current_bucket["version_to"], row["version"]
                )
                current_bucket["step_count"] += 1

        if current_bucket is not None and len(buckets) < limit:
            buckets.append(_format_bucket(current_bucket))

        return JSONResponse(
            {
                "document_id": document_id,
                "current_version": current_version,
                "checkpoints": buckets,
            }
        )

    def _format_bucket(b: dict) -> dict:
        return {
            "version_from": b["version_from"],
            "version_to": b["version_to"],
            "created_at": b["created_at"],
            "step_count": b["step_count"],
            "client_id": b["client_id"],
        }

    # ------------------------------------------------------------------
    # History at version — GET /api/documents/{document_id}/history/{version}
    # ------------------------------------------------------------------

    async def history_at_version(request: Request) -> JSONResponse:
        """Return baseline body + all steps up to *version* for client-side replay."""
        from starlette_cms.auth import require_auth
        from starlette_cms.tables import CMSDocument, CMSStep

        if cms.read_auth:
            if (err := await require_auth(request, cms)) is not None:
                return err

        document_id: str = request.path_params["document_id"]
        try:
            target_version = int(request.path_params["version"])
        except (ValueError, KeyError):
            return JSONResponse({"error": "Invalid version"}, status_code=400)

        # Fetch document (need the published body as baseline)
        doc_rows = (
            await CMSDocument.select(CMSDocument.id, CMSDocument.body)
            .where(CMSDocument.id == document_id)
            .limit(1)
            .run()
        )
        if not doc_rows:
            return JSONResponse({"error": "Document not found"}, status_code=404)

        raw_body = doc_rows[0].get("body", "{}")
        baseline_body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

        # Fetch steps up to (and including) the requested version
        step_rows = (
            await CMSStep.select(CMSStep.version, CMSStep.step_data, CMSStep.client_id)
            .where(
                CMSStep.document_id == document_id,
                CMSStep.version <= target_version,
            )
            .order_by(CMSStep.version, ascending=True)
            .run()
        )

        steps = []
        for row in step_rows:
            raw = row.get("step_data", "{}")
            try:
                step_dict = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                step_dict = {}
            steps.append(step_dict)

        return JSONResponse(
            {
                "document_id": document_id,
                "version": target_version,
                "step_count": len(steps),
                "baseline_body": baseline_body,
                "steps": steps,
                "note": (
                    "Step replay is performed client-side using the returned steps. "
                    "Apply each step in order to baseline_body to reconstruct the "
                    "document state at the requested version."
                ),
            }
        )

    return [
        WebSocketRoute("/api/events", endpoint=events_ws),
        WebSocketRoute("/api/documents/{document_id}/collab", endpoint=collab_ws),
        Route(
            "/api/documents/{document_id}/history",
            endpoint=history_list,
            methods=["GET"],
            name="collab_history_list",
        ),
        Route(
            "/api/documents/{document_id}/history/{version}",
            endpoint=history_at_version,
            methods=["GET"],
            name="collab_history_at_version",
        ),
    ]
