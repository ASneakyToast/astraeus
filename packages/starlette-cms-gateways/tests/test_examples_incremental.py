"""
Tests for incremental sync behaviour in the iNaturalist example gateway.

Uses ``respx`` to mock the iNaturalist HTTP API — no network calls are made.
The ``conftest.py`` in this directory adds ``examples/`` to ``sys.path``
so the example gateways can be imported directly.

The Spotify example deliberately has no cursor (it fetches everything and relies
on content-hash skips), so its test pins that: a stored cursor changes nothing.
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


async def test_spotify_example_has_no_cursor_and_reads_every_page_whatever_is_stored():
    """The no-cursor example: a stored cursor is ignored, and every page is read."""
    from spotify_liked_songs.gateway import SpotifyLikedSongsGateway
    from starlette_cms_gateways.client import CMSClient
    from starlette_cms_gateways.jobstore import JobStore

    def track(i: str, added: str) -> dict:
        return {"added_at": added, "track": {"id": i, "name": f"T{i}", "artists": [{"name": "A"}]}}

    pages = [
        {"items": [track("1", "2026-09-02T00:00:00Z")], "next": "more"},
        {"items": [track("2", "2020-01-01T00:00:00Z")], "next": None},  # years before the cursor
    ]

    class FakeSp:
        def __init__(self) -> None:
            self.offsets: list[int] = []

        def current_user_saved_tracks(self, limit: int, offset: int) -> dict:
            self.offsets.append(offset)
            return pages[len(self.offsets) - 1]

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = JobStore(db_path)
        await store.set_cursor("spotify_liked_songs", datetime(2026, 9, 10, tzinfo=UTC))
        stub = {"spotipy": MagicMock(), "spotipy.oauth2": MagicMock()}  # not installed here
        with patch.dict("sys.modules", stub):
            gw = SpotifyLikedSongsGateway(cms_client=MagicMock(spec=CMSClient), job_store=store)
        gw._sp = FakeSp()

        items = [i async for i in gw.fetch()]

        assert [i.import_ref for i in items] == ["spotify:liked:1", "spotify:liked:2"]
        assert gw._sp.offsets == [0, 50]
        assert gw._window is None, "never asked for a window, so no cursor is kept"
    finally:
        os.unlink(db_path)
