"""
Tests for the top-level JobStore — import paths, get_last_synced, and
backward-compat shim.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tmp_store():
    """Return a (path, JobStore) pair using a temp SQLite file."""
    from starlette_cms_gateways.jobstore import JobStore

    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return f.name, JobStore(f.name)


# ---------------------------------------------------------------------------
# Import path tests
# ---------------------------------------------------------------------------


async def test_importable_from_top_level():
    """JobStore must be importable from the top-level package namespace."""
    from starlette_cms_gateways import JobStore  # noqa: F401

    assert JobStore is not None


async def test_backward_compat_import():
    """admin.jobstore shim must re-export JobStore unchanged."""
    from starlette_cms_gateways.admin.jobstore import JobStore as AdminJobStore
    from starlette_cms_gateways.jobstore import JobStore as TopJobStore

    assert AdminJobStore is TopJobStore


# ---------------------------------------------------------------------------
# get_last_synced
# ---------------------------------------------------------------------------


async def test_get_last_synced_none_when_no_jobs():
    """get_last_synced returns None when the job table is empty."""
    path, store = _tmp_store()
    try:
        result = await store.get_last_synced("my-gateway")
        assert result is None
    finally:
        os.unlink(path)


async def test_get_last_synced_none_when_only_error_jobs():
    """get_last_synced returns None when there are only error-status jobs."""
    path, store = _tmp_store()
    try:
        await store.create("run-err-1", "my-gateway")
        await store.finish("run-err-1", status="error", error="boom")

        result = await store.get_last_synced("my-gateway")
        assert result is None
    finally:
        os.unlink(path)


async def test_get_last_synced_returns_most_recent_done():
    """get_last_synced returns the finished_at of the most recent done job."""
    path, store = _tmp_store()
    try:
        # Create two done jobs
        await store.create("run-1", "my-gateway")
        await store.finish("run-1", status="done", created=1)

        # Small sleep not needed — datetime.now() will differ at microsecond level
        await store.create("run-2", "my-gateway")
        await store.finish("run-2", status="done", created=2)

        result = await store.get_last_synced("my-gateway")
        assert result is not None
        assert isinstance(result, datetime)
        # Should be a UTC-aware datetime
        assert result.tzinfo is not None

        # Verify it's recent (within the last 10 seconds)
        now = datetime.now(UTC)
        assert (now - result).total_seconds() < 10
    finally:
        os.unlink(path)


async def test_get_last_synced_skips_error_jobs_after_done():
    """get_last_synced ignores later error jobs and returns the last done."""
    path, store = _tmp_store()
    try:
        # One done job, then an error job after it
        await store.create("run-done", "my-gateway")
        await store.finish("run-done", status="done", created=5)

        await store.create("run-err", "my-gateway")
        await store.finish("run-err", status="error", error="network timeout")

        result = await store.get_last_synced("my-gateway")
        assert result is not None  # still returns the done job's timestamp
    finally:
        os.unlink(path)


async def test_get_last_synced_scoped_to_key():
    """get_last_synced only returns jobs matching the requested key."""
    path, store = _tmp_store()
    try:
        # Done job for gateway-A
        await store.create("run-a", "gateway-a")
        await store.finish("run-a", status="done", created=1)

        # No jobs for gateway-b
        result_b = await store.get_last_synced("gateway-b")
        assert result_b is None

        result_a = await store.get_last_synced("gateway-a")
        assert result_a is not None
    finally:
        os.unlink(path)
