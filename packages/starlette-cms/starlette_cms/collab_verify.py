"""
Server-side verification of collaborative editing steps (ADR 024 spike, Path A1).

``CollabAuthority`` used to accept the client's post-edit document on trust.
When verification is enabled it instead applies every step to the server's own
copy with a Python port of ``prosemirror-model`` / ``prosemirror-transform``
(the ``prosemirror`` package, installed with the ``collab-verify`` extra), so
the stored document is the one the steps produce, and a step that would break
the schema is rejected rather than stored.

The schema must match the editor's (``editor_src/prosemirror/schema.js``): the
basic schema plus ordered and bullet lists. Steps built against any other
schema fail to parse here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from prosemirror.model import Schema

#: What an empty rich-text field looks like to the editor.
EMPTY_DOC: dict[str, Any] = {"type": "doc", "content": [{"type": "paragraph"}]}


@lru_cache(maxsize=1)
def editor_schema() -> Schema:
    """The ProseMirror schema both editing surfaces use, built in Python.

    Mirrors ``schemaWithLists`` in the editor: ``prosemirror-schema-basic``
    plus ``addListNodes(nodes, 'paragraph block*', 'block')``.

    :raises ImportError: if the ``collab-verify`` extra is not installed.
    """
    from prosemirror.model import Schema
    from prosemirror.schema.basic import schema as basic
    from prosemirror.schema.list import add_list_nodes

    nodes = add_list_nodes(basic.spec["nodes"], "paragraph block*", "block")
    return Schema({"nodes": nodes, "marks": basic.spec["marks"]})


@dataclass
class ApplyOutcome:
    """Result of applying a batch of steps to a document."""

    ok: bool
    #: The resulting document as ProseMirror JSON (``None`` when ``ok`` is false).
    doc: dict[str, Any] | None = None
    #: Why the batch was refused: the index of the failing step and the reason.
    reason: str | None = None


def apply_steps(schema: Schema, doc_json: dict[str, Any] | None, steps: list[dict]) -> ApplyOutcome:
    """Apply *steps* to *doc_json* in order, all or nothing.

    Never raises for bad input: a step that does not parse, does not apply, or
    would leave a node with content its schema forbids is a refusal. Applying a
    step can raise as well as return a failed result (``prosemirror`` raises
    ``ValueError`` for invalid content), so both are handled.
    """
    from prosemirror.transform import Step

    try:
        doc = schema.node_from_json(doc_json or EMPTY_DOC)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a refusal
        return ApplyOutcome(False, reason=f"server document does not fit the schema: {exc}")

    for index, raw in enumerate(steps):
        try:
            step = Step.from_json(schema, raw)
            result = step.apply(doc)
        except Exception as exc:  # noqa: BLE001
            return ApplyOutcome(False, reason=f"step {index} could not be applied: {exc}")
        if result.failed or result.doc is None:
            return ApplyOutcome(False, reason=f"step {index} failed: {result.failed}")
        doc = result.doc

    return ApplyOutcome(True, doc=doc.to_json())


def docs_equal(schema: Schema, a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    """True if two ProseMirror JSON documents are the same document under *schema*.

    A document that does not fit the schema is never equal to anything.
    """
    try:
        return schema.node_from_json(a or EMPTY_DOC).eq(schema.node_from_json(b or EMPTY_DOC))
    except Exception:  # noqa: BLE001
        return False
