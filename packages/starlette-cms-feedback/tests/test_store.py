"""FeedbackStore — persistence and triage semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette_cms_feedback import (
    FeedbackCreate,
    FeedbackKind,
    FeedbackSeverity,
    FeedbackStatus,
    FeedbackStore,
    FeedbackUpdate,
)

pytestmark = pytest.mark.asyncio


def _report(**overrides: Any) -> FeedbackCreate:
    fields: dict[str, Any] = {
        "description": "It broke.",
        "kind": FeedbackKind.BUG,
        "title": "Editor crashes",
    }
    return FeedbackCreate(**{**fields, **overrides})


@pytest.fixture
def store(tmp_path: Path) -> FeedbackStore:
    return FeedbackStore(tmp_path / "feedback.db")


async def test_create_starts_new(store: FeedbackStore):
    report = await store.create(_report())

    assert report.status is FeedbackStatus.NEW
    assert report.created_at == report.updated_at
    assert await store.get(report.id) == report


async def test_get_missing_returns_none(store: FeedbackStore):
    assert await store.get("nope") is None


async def test_update_changes_only_sent_fields(store: FeedbackStore):
    report = await store.create(_report(severity=FeedbackSeverity.LOW))

    updated = await store.update(report.id, FeedbackUpdate(status=FeedbackStatus.TRIAGED))

    assert updated is not None
    assert updated.status is FeedbackStatus.TRIAGED
    assert updated.severity is FeedbackSeverity.LOW  # untouched
    assert updated.updated_at >= report.updated_at


async def test_update_explicit_none_clears_field(store: FeedbackStore):
    report = await store.create(_report(severity=FeedbackSeverity.HIGH))

    updated = await store.update(report.id, FeedbackUpdate(severity=None))

    assert updated is not None
    assert updated.severity is None


async def test_update_missing_returns_none(store: FeedbackStore):
    result = await store.update("nope", FeedbackUpdate(status=FeedbackStatus.FIXED))

    assert result is None


async def test_list_filters_and_total_ignores_paging(store: FeedbackStore):
    await store.create(_report(title="a", component="starlette-editor"))
    await store.create(_report(title="b", kind=FeedbackKind.IDEA))
    fixed = await store.create(_report(title="c"))
    await store.update(fixed.id, FeedbackUpdate(status=FeedbackStatus.FIXED))

    bugs, bug_total = await store.list_reports(kind=FeedbackKind.BUG, limit=1)
    assert len(bugs) == 1
    assert bug_total == 2

    done, _ = await store.list_reports(status=FeedbackStatus.FIXED)
    assert [r.title for r in done] == ["c"]

    editor, _ = await store.list_reports(component="starlette-editor")
    assert [r.title for r in editor] == ["a"]


async def test_list_is_newest_first(store: FeedbackStore):
    await store.create(_report(title="first"))
    await store.create(_report(title="second"))

    reports, _ = await store.list_reports()

    assert [r.title for r in reports] == ["second", "first"]
