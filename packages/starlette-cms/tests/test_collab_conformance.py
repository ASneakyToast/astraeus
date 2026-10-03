"""
T12 (ADR 024): steps built by the editor's own prosemirror-transform apply in
``prosemirror-py`` to the same document.

The fixtures come from ``packages/starlette-editor/scripts/gen-collab-fixtures.mjs``,
which uses the editor's schema and the JS ``prosemirror-transform`` that the
editor bundles. Regenerate them when either side's version moves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("prosemirror", reason="needs the collab-verify extra")

from starlette_cms.collab_verify import apply_steps, docs_equal, editor_schema  # noqa: E402

_FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "collab_steps.json").read_text())
_CASES = _FIXTURES["cases"]


def test_fixtures_record_the_js_versions_they_came_from():
    """The skew between the JS editor and the Python port is part of the evidence."""
    versions = _FIXTURES["generatedWith"]
    assert set(versions) == {"prosemirror-transform", "prosemirror-model"}


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_python_reaches_the_same_document_as_the_editor(case):
    schema = editor_schema()
    outcome = apply_steps(schema, case["start"], case["steps"])

    assert outcome.ok, outcome.reason
    assert docs_equal(schema, outcome.doc, case["end"]), (
        f"{case['name']}: python produced\n{json.dumps(outcome.doc)}\nbut the editor produced\n"
        f"{json.dumps(case['end'])}"
    )


def test_every_step_type_the_editor_emits_is_covered():
    """If the editor starts emitting a new step type, add a case for it."""
    seen = {step["stepType"] for case in _CASES for step in case["steps"]}
    assert {"replace", "replaceAround", "addMark", "removeMark", "attr"} <= seen


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_the_comparison_can_fail(case):
    """Guard against a vacuous pass: each batch must actually change the document."""
    schema = editor_schema()
    assert not docs_equal(schema, case["start"], case["end"])
