"""Tests for GatewayItem and SyncResult dataclasses."""

from __future__ import annotations

from datetime import UTC, datetime

from starlette_cms_gateways.base import GatewayItem, SyncResult


# ---------------------------------------------------------------------------
# GatewayItem
# ---------------------------------------------------------------------------


def test_gateway_item_content_hash_is_stable():
    item = GatewayItem(
        import_ref="svc:type:001",
        slug="svc-type-001",
        body={"title": "Hello", "value": 42},
    )
    h1 = item.content_hash()
    h2 = item.content_hash()
    assert h1 == h2
    assert len(h1) == 16  # 16-char hex digest


def test_gateway_item_content_hash_differs_on_body_change():
    base = GatewayItem(
        import_ref="svc:type:001",
        slug="svc-type-001",
        body={"title": "Hello"},
    )
    changed = GatewayItem(
        import_ref="svc:type:001",
        slug="svc-type-001",
        body={"title": "Hello world"},
    )
    assert base.content_hash() != changed.content_hash()


def test_gateway_item_hash_independent_of_key_order():
    item1 = GatewayItem(
        import_ref="a",
        slug="a",
        body={"z": 1, "a": 2},
    )
    item2 = GatewayItem(
        import_ref="a",
        slug="a",
        body={"a": 2, "z": 1},
    )
    assert item1.content_hash() == item2.content_hash()


def test_gateway_item_published_defaults_to_none():
    item = GatewayItem(import_ref="r", slug="s", body={})
    assert item.published is None


# ---------------------------------------------------------------------------
# SyncResult
# ---------------------------------------------------------------------------


def test_sync_result_total():
    r = SyncResult(created=3, updated=2, skipped=10)
    assert r.total == 15


def test_sync_result_has_errors_false():
    r = SyncResult()
    assert not r.has_errors


def test_sync_result_has_errors_true():
    r = SyncResult(errors=[("ref:001", "timeout")])
    assert r.has_errors


def test_sync_result_finish_sets_finished_at():
    r = SyncResult()
    assert r.finished_at is None
    r.finish()
    assert r.finished_at is not None


def test_sync_result_to_dict():
    r = SyncResult(created=1, updated=2, skipped=3)
    r.finish()
    d = r.to_dict()
    assert d["created"] == 1
    assert d["updated"] == 2
    assert d["skipped"] == 3
    assert d["total"] == 6
    assert d["finished_at"] is not None
    assert d["errors"] == []
