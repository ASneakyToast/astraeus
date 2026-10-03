"""
A throwaway CMS for the browser-less end-to-end collab harness (ADR 024 spike).

``packages/starlette-editor/scripts/e2e-collab.mjs`` starts this and drives it with
the editor's real ``CollabConnection`` and ``prosemirror-collab``.

Modes:

``verify``  the spike: steps are applied and checked server-side, catch-up works
``legacy``  main today: the client's document is stored on trust, no catch-up
``bug34``   legacy plus the bug fixed in #34: one client ID for a whole batch
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
import time

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS, RichTextField, TextField
from starlette_cms.collab import CollabAuthority, CollabManager


def _trace_connections() -> None:
    """Print connection lifecycle and any send that takes more than half a second."""
    add, remove = CollabManager.add_connection, CollabManager.remove_connection

    async def traced_add(self, room, ws):
        print(f"TRACE add    ws={id(ws) % 10000}", flush=True)
        return await add(self, room, ws)

    async def traced_remove(self, room, ws):
        print(f"TRACE remove ws={id(ws) % 10000}", flush=True)
        return await remove(self, room, ws)

    async def traced_broadcast(self, document_id, message, exclude=None):
        for ws in set(self._connections.get(document_id, set())):
            if ws is exclude:
                continue
            started = time.monotonic()
            try:
                await ws.send_json(message)
            except Exception as exc:  # noqa: BLE001
                print(f"TRACE send to ws={id(ws) % 10000} failed: {type(exc).__name__}", flush=True)
            took = time.monotonic() - started
            if took > 0.5:
                print(f"TRACE SLOW send to ws={id(ws) % 10000} took {took:.1f}s", flush=True)

    CollabManager.add_connection = traced_add  # type: ignore[method-assign]
    CollabManager.remove_connection = traced_remove  # type: ignore[method-assign]
    CollabManager.broadcast = traced_broadcast  # type: ignore[method-assign]


def build(mode: str, db_path: str) -> Starlette:
    cms = CMS(
        database_url=f"sqlite:///{db_path}",
        auth="none",
        read_auth=False,
        verify_collab=(mode == "verify"),
    )

    @cms.block("article")
    class Article:
        title: str = TextField(required=True)
        body: dict = RichTextField()

    if mode == "bug34":
        original = CollabAuthority.apply_steps

        def one_client_id_per_batch(self, *args, **kwargs):
            result = original(self, *args, **kwargs)
            result.client_ids = result.client_ids[:1]
            return result

        CollabAuthority.apply_steps = one_client_id_per_batch  # type: ignore[method-assign]

    if os.environ.get("COLLAB_TRACE"):
        _trace_connections()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        # `kill -USR1 <pid>` prints where every task is waiting; the harness uses
        # this to see what a stuck connection is blocked on.
        def dump() -> None:
            for task in asyncio.all_tasks():
                task.print_stack()

        asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, dump)
        async with cms.lifespan(app):
            yield

    return Starlette(routes=[Mount("/", app=cms.app)], lifespan=lifespan)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["verify", "legacy", "bug34"], required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    uvicorn.run(build(args.mode, args.db), host="127.0.0.1", port=args.port, log_level="warning")
