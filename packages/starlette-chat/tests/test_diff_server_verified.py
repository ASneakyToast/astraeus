"""
T2 (ADR 024): the steps the AI peer sends apply, on the server, to the document
the AI peer claims they produce.

``tools.py`` sends ``steps`` from ``diff_docs`` together with ``"doc": new_doc``.
Today the server stores ``new_doc`` on trust. With verification the server applies
the steps itself, so a ``diff_docs`` bug (a wrong position, a wrong node size)
turns into a refused or mismatching edit instead of silent divergence.
"""

from __future__ import annotations

import random

import pytest

pytest.importorskip("prosemirror", reason="needs the starlette-cms collab-verify extra")

from starlette_chat.diff import diff_docs  # noqa: E402
from starlette_chat.prosemirror import markdown_to_pm  # noqa: E402
from starlette_cms.collab_verify import apply_steps, docs_equal, editor_schema  # noqa: E402

BLOCKS = [
    "# A heading",
    "## Another heading",
    "A plain paragraph.",
    "A paragraph with **bold** and *italic* and `code`.",
    "Two lines  \nwith a hard break.",
    "> A quoted line",
    "- one\n- two\n- three",
    "1. first\n2. second",
    "```\ncode block\n```",
    "---",
    "![alt text](https://example.com/a.png)",
    "A [link](https://example.com) in a paragraph.",
]


def _markdown(blocks: list[str]) -> str:
    return "\n\n".join(blocks)


def _check(current_md: str, new_md: str) -> str | None:
    """None if the diff applies cleanly to the new document, else what went wrong."""
    schema = editor_schema()
    current, new = markdown_to_pm(current_md), markdown_to_pm(new_md)
    steps = diff_docs(current, new)
    outcome = apply_steps(schema, current, steps)
    if not outcome.ok:
        return f"refused: {outcome.reason}"
    if not docs_equal(schema, outcome.doc, new):
        return "applied, but the result is not the document the AI peer claimed"
    return None


@pytest.mark.parametrize("block", BLOCKS)
def test_replacing_a_single_block_with_another_kind(block):
    other = "A different paragraph."
    before = _markdown(["First.", block, "Last."])
    after = _markdown(["First.", other, "Last."])
    assert _check(before, after) is None


@pytest.mark.parametrize("block", BLOCKS)
def test_inserting_a_block_before_and_after_existing_content(block):
    base = _markdown(["Existing paragraph.", "Another one."])
    assert _check(base, _markdown([block, "Existing paragraph.", "Another one."])) is None
    assert _check(base, _markdown(["Existing paragraph.", "Another one.", block])) is None


@pytest.mark.parametrize("block", BLOCKS)
def test_deleting_a_block(block):
    before = _markdown(["Keep.", block, "Keep too."])
    assert _check(before, _markdown(["Keep.", "Keep too."])) is None


def test_randomised_rewrites_apply_to_exactly_the_claimed_document():
    """200 seeded random rewrites of a document made of the block kinds above."""
    rng = random.Random(24)
    failures: list[str] = []
    for n in range(200):
        before = [rng.choice(BLOCKS) for _ in range(rng.randint(1, 6))]
        after = [rng.choice(BLOCKS) for _ in range(rng.randint(1, 6))]
        problem = _check(_markdown(before), _markdown(after))
        if problem:
            failures.append(f"#{n} {problem}\n  before={before}\n  after={after}")
    assert not failures, f"{len(failures)} of 200 failed:\n" + "\n".join(failures[:5])
