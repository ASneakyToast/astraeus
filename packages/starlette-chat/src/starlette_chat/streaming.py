"""
Streaming event serialization helpers for starlette-chat.

StreamEvents produced by the provider are forwarded directly to the browser
WebSocket as JSON objects.  This module provides ``event_to_dict`` which
converts a :class:`~starlette_chat.providers.base.StreamEvent` to a
JSON-serialisable dict for ``websocket.send_json()``.
"""

from __future__ import annotations

from starlette_chat.providers.base import StreamEvent


def event_to_dict(event: StreamEvent) -> dict:
    """Serialise a :class:`StreamEvent` to a JSON-ready dict.

    The ``type`` key is always present.  All keys from ``event.data`` are
    merged at the top level so that the browser can read them without
    nesting::

        >>> event_to_dict(StreamEvent(type="token", data={"delta": "hello"}))
        {'type': 'token', 'delta': 'hello'}
    """
    result: dict = {"type": event.type}
    result.update(event.data)
    return result
