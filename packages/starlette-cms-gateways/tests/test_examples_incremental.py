"""
Tests for incremental sync behaviour in the iNaturalist example gateway.

Uses ``respx`` to mock the iNaturalist HTTP API — no network calls are made.
The ``conftest.py`` in this directory adds ``examples/`` to ``sys.path``
so the example gateways can be imported directly.

Spotify incremental test:
# TODO: test incremental sync for spotify — requires mocking spotipy at
# sys.modules level (it's synchronous and imported in __init__), which is
# more involved than the httpx-based iNaturalist mock.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OBS_RESPONSE = {
    "total_results": 1,
    "results": [
        {
            "id": 12345,
            "taxon": {
                "name": "Apis mellifera",
                "preferred_common_name": "Western Honey Bee",
            },
            "species_guess": "Western Honey Bee",
            "observed_on": "2024-06-01",
            "place_guess": "Central Park",
            "location": "40.785,-73.968",
            "quality_grade": "research",
            "photos": [{"url": "https://example.com/photo.jpg"}],
        }
    ],
}

_EMPTY_RESPONSE = {"total_results": 0, "results": []}


def _make_gateway(job_store=None):
    """Create an INaturalistGateway with INATURALIST_USERNAME set."""
    from inaturalist_outings.gateway import INaturalistGateway
    from starlette_cms_gateways.client import CMSClient

    # Minimal mock client — not actually called in these unit tests
    mock_client = MagicMock(spec=CMSClient)

    with patch.dict(os.environ, {"INATURALIST_USERNAME": "testuser"}):
        return INaturalistGateway(cms_client=mock_client, job_store=job_store)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
async def test_full_fetch_when_no_job_store():
    """
    When no job_store is provided, no d1 param is sent — full fetch.
    """
    route = respx.get("https://api.inaturalist.org/v1/observations").mock(
        side_effect=[
            Response(200, json=_OBS_RESPONSE),
            Response(200, json=_EMPTY_RESPONSE),
        ]
    )

    gw = _make_gateway(job_store=None)
    items = [item async for item in gw.fetch()]

    assert len(items) == 1
    assert items[0].import_ref == "inaturalist:observation:12345"

    # Verify no d1 param was sent
    for call in route.calls:
        assert "d1" not in dict(call.request.url.params)


@respx.mock
async def test_incremental_fetch_sends_d1_param():
    """
    When job_store has a successful done job, d1 is sent to the API.
    """

    # Create a real (temp-file) job store with a completed job
    from starlette_cms_gateways.jobstore import JobStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = JobStore(db_path)
        await store.create("run-1", "inaturalist_outings")
        await store.finish("run-1", status="done", created=10)

        route = respx.get("https://api.inaturalist.org/v1/observations").mock(
            side_effect=[
                Response(200, json=_OBS_RESPONSE),
                Response(200, json=_EMPTY_RESPONSE),
            ]
        )

        gw = _make_gateway(job_store=store)
        items = [item async for item in gw.fetch()]

        assert len(items) == 1

        # Verify d1 param was sent
        first_call = route.calls[0]
        params = dict(first_call.request.url.params)
        assert "d1" in params, f"Expected d1 param, got: {params}"
        # d1 should be a date string (YYYY-MM-DD)
        d1_val = params["d1"]
        # Should parse as a valid date
        from datetime import date

        date.fromisoformat(d1_val)  # raises ValueError on invalid format
    finally:
        os.unlink(db_path)


@respx.mock
async def test_no_d1_when_only_error_jobs():
    """
    When job_store exists but only has error jobs, no d1 is sent.
    """
    from starlette_cms_gateways.jobstore import JobStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = JobStore(db_path)
        await store.create("run-err", "inaturalist_outings")
        await store.finish("run-err", status="error", error="timeout")

        route = respx.get("https://api.inaturalist.org/v1/observations").mock(
            side_effect=[
                Response(200, json=_OBS_RESPONSE),
                Response(200, json=_EMPTY_RESPONSE),
            ]
        )

        gw = _make_gateway(job_store=store)
        items = [item async for item in gw.fetch()]

        assert len(items) == 1

        # No d1 param since no successful prior sync
        first_call = route.calls[0]
        params = dict(first_call.request.url.params)
        assert "d1" not in params, f"d1 should not be present, got: {params}"
    finally:
        os.unlink(db_path)
