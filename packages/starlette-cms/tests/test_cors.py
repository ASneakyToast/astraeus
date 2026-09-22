"""CORS exposure for the auto-changeset response headers.

The embed edits from the published site, cross-origin to the CMS, and adopts a
server-created changeset from X-Changeset-Id on the PATCH response. CORS hides
response headers from cross-origin JS unless they are exposed, so without this
the embed could never see the header — only the same-origin shell could.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport
from starlette_cms import CMS

ORIGIN = "https://joellithgow.com"


@pytest.fixture
def cms() -> CMS:
    return CMS(
        database_url="sqlite:///:memory:",
        auth=None,
        read_auth=False,
        cors_origins=[ORIGIN],
    )


@pytest.mark.anyio
async def test_changeset_headers_are_exposed_cross_origin(cms: CMS) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=cms.app), base_url="http://test"
    ) as client:
        res = await client.get("/api/schema", headers={"Origin": ORIGIN})

    exposed = res.headers.get("access-control-expose-headers", "")
    assert "X-Changeset-Id" in exposed
    assert "X-Changeset-Title" in exposed
