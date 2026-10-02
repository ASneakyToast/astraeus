"""
Whose draft is it?

A PATCH on a published document never edits the live body: it writes a pending
draft. So when a gateway finds a draft on a document it is about to update, it
has to tell its own leftover (a PATCH whose publish failed, or a revision
waiting on review) from somebody's work in progress.

The test is what the draft changes. A draft that differs from the live body only
in fields the gateway owns is the gateway's. One that touches anything else is a
person's, and is left alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Literal

DraftVerdict = Literal["none", "gateway-only", "human-edits"]


def norm(value: Any) -> Any:
    """Round-trip through JSON so 2 and 2.0, and tuples and lists, compare as stored."""
    return json.loads(json.dumps(value, sort_keys=True))


def draft_verdict(
    live: dict[str, Any],
    draft: dict[str, Any] | None,
    owned_fields: Iterable[str] | None,
    *,
    ignore: Iterable[str] = (),
) -> tuple[DraftVerdict, list[str]]:
    """
    Classify *draft* against the live body.

    :returns: ``(verdict, differing_fields)`` where the verdict is ``"none"``
        (no draft), ``"gateway-only"`` (every changed field is owned) or
        ``"human-edits"`` (something else changed).
    :param owned_fields: The gateway's owned fields. ``None`` means the gateway
        did not declare any, so nothing can be told apart: any draft is a
        person's.
    :param ignore: Keys to leave out of the comparison (a stray key the model
        drops on every write, say).
    """
    if not draft:
        return "none", []
    skip = set(ignore)
    keys = (set(live) | set(draft)) - skip
    differing = sorted(k for k in keys if norm(live.get(k)) != norm(draft.get(k)))
    if owned_fields is None:
        return "human-edits", differing
    owned = set(owned_fields)
    return ("human-edits" if any(k not in owned for k in differing) else "gateway-only"), differing
