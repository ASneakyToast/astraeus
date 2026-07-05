"""
Example gateway: iNaturalist Observations

Pulls wildlife observations from the iNaturalist API for a given username
and creates one CMS document per observation using the
``inaturalist_observation`` block type.

This is a **reference implementation** — it lives in examples/ and is not
installed as part of starlette-cms-gateways.  Copy it into your own application
and adapt to your needs.

Dependencies (not declared in the package):
- httpx >= 0.27 (already installed as a gateway dependency)

No API key required for public observations.

Setup:
    export INATURALIST_USERNAME=your-inaturalist-username

Register in your pyproject.toml::

    [project.entry-points."starlette_cms_gateways.gateways"]
    inaturalist-outings = "myapp.gateways.inaturalist:INaturalistGateway"

Then sync::

    gateways sync inaturalist-outings \\
        --cms-url https://cms.example.com \\
        --api-key $CMS_API_KEY
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
from starlette_cms_gateways import BaseGateway, GatewayItem

INATURALIST_API = "https://api.inaturalist.org/v1"


class INaturalistGateway(BaseGateway):
    """
    Sync iNaturalist observations into starlette-cms.

    Each observation becomes one document of block type
    ``inaturalist_observation``.

    Incremental sync: if a :class:`~starlette_cms_gateways.jobstore.JobStore`
    is provided (automatically wired when running via ``GatewayAdmin``), the
    gateway reads the timestamp of the most recent successful sync and passes
    it to the iNaturalist API as the ``d1`` date filter.  This limits the
    fetch to only observations updated on or after that date.  Using ``.date()``
    is intentionally conservative to avoid gaps at day boundaries.

    Configuration via environment variables:
    - ``INATURALIST_USERNAME`` — the iNaturalist account to pull observations for
    """

    service_name = "inaturalist_outings"
    block_type = "inaturalist_observation"
    auto_publish = False  # Hold as drafts; publish after review. Set True to auto-publish.

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._username = os.environ.get("INATURALIST_USERNAME", "")
        if not self._username:
            raise ValueError(
                "INATURALIST_USERNAME environment variable is required for "
                "INaturalistGateway."
            )

    async def fetch(self) -> AsyncIterator[GatewayItem]:
        """
        Yield observations from iNaturalist, paginating through all results.

        Uses the public iNaturalist v1 API.  No authentication required for
        public observations.

        When a job store is available, passes ``d1`` (start date) to the API
        to fetch only observations since the last successful sync.  ``d1`` is
        a date (not datetime); using ``.date()`` is intentionally conservative
        to avoid gaps at day boundaries.
        """
        # Determine the cursor for incremental sync.
        since: datetime | None = None
        if self._job_store is not None:
            since = await self._job_store.get_last_synced(self._job_store_key)

        params: dict[str, object] = {
            "user_login": self._username,
            "order": "asc",
            "order_by": "observed_on",
            "per_page": 200,
        }

        if since is not None:
            # d1 is a date, not datetime; using .date() is intentionally conservative
            # to include observations from the same day as the last sync.
            params["d1"] = since.date().isoformat()  # YYYY-MM-DD

        page = 1

        async with httpx.AsyncClient(timeout=30.0) as http:
            while True:
                params["page"] = page
                resp = await http.get(f"{INATURALIST_API}/observations", params=params)
                resp.raise_for_status()
                data = resp.json()

                results = data.get("results") or []
                if not results:
                    break

                for obs in results:
                    obs_id = obs.get("id")
                    if obs_id is None:
                        continue

                    taxon = obs.get("taxon") or {}
                    preferred_name = (
                        taxon.get("preferred_common_name")
                        or taxon.get("name")
                        or obs.get("species_guess")
                        or "Unknown species"
                    )

                    # Collect photo URLs (small square thumbnails)
                    photos = obs.get("photos") or []
                    photo_urls = [
                        p.get("url", "").replace("square", "medium")
                        for p in photos
                        if p.get("url")
                    ]

                    # Location
                    geo = obs.get("location") or ""
                    lat, lon = 0.0, 0.0
                    if geo and "," in geo:
                        try:
                            lat_s, lon_s = geo.split(",", 1)
                            lat, lon = float(lat_s), float(lon_s)
                        except ValueError:
                            pass

                    observed_on = obs.get("observed_on") or obs.get("time_observed_at", "")
                    place = obs.get("place_guess") or ""

                    yield GatewayItem(
                        import_ref=f"inaturalist:observation:{obs_id}",
                        slug=f"inaturalist-{obs_id}",
                        title=f"{preferred_name} — {place or observed_on}",
                        body={
                            "species_guess": obs.get("species_guess") or preferred_name,
                            "taxon_name": taxon.get("name") or "",
                            "common_name": taxon.get("preferred_common_name") or "",
                            "observed_on": observed_on,
                            "place_guess": place,
                            "latitude": lat,
                            "longitude": lon,
                            "quality_grade": obs.get("quality_grade") or "",
                            "inaturalist_url": (
                                f"https://www.inaturalist.org/observations/{obs_id}"
                            ),
                            "photo_urls": photo_urls,
                        },
                    )

                total_results = data.get("total_results", 0)
                if page * 200 >= total_results:
                    break
                page += 1
