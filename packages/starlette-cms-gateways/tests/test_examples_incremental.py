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
from datetime import UTC, datetime
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
    When no job_store is provided, no cursor param is sent — full fetch.
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

    for call in route.calls:
        assert "updated_since" not in dict(call.request.url.params)


@respx.mock
async def test_incremental_fetch_sends_d1_param():
    """
    When the job store holds a cursor, it is sent to the API as updated_since.
    """

    # Create a real (temp-file) job store with a completed job
    from starlette_cms_gateways.jobstore import JobStore

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        store = JobStore(db_path)
        cursor = datetime(2026, 9, 10, 12, tzinfo=UTC)
        await store.set_cursor("inaturalist_outings", cursor)

        route = respx.get("https://api.inaturalist.org/v1/observations").mock(
            side_effect=[
                Response(200, json=_OBS_RESPONSE),
                Response(200, json=_EMPTY_RESPONSE),
            ]
        )

        gw = _make_gateway(job_store=store)
        items = [item async for item in gw.fetch()]

        assert len(items) == 1

        params = dict(route.calls[0].request.url.params)
        assert "updated_since" in params, f"Expected updated_since, got: {params}"
        # The cursor, pulled back by the gateway's overlap.
        assert datetime.fromisoformat(params["updated_since"]) == cursor - gw.cursor_overlap
    finally:
        os.unlink(db_path)


@respx.mock
async def test_no_d1_when_only_error_jobs():
    """
    A failed run stores no cursor, so a store holding only error jobs sends nothing.
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

        params = dict(route.calls[0].request.url.params)
        assert "updated_since" not in params, f"no cursor was stored, got: {params}"
    finally:
        os.unlink(db_path)
