"""Tests for the shared design-token stylesheet served by starlette-cms.

Every admin surface consumes this file (ADR 020 §4), so it has to be reachable
from the CMS mount rather than copied per package.
"""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from starlette_cms import CMS


@pytest.fixture
def cms() -> CMS:
    return CMS(database_url="sqlite:///:memory:", auth=None, read_auth=False)


@pytest.mark.anyio
async def test_tokens_stylesheet_is_served(cms: CMS) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=cms.app), base_url="http://test"
    ) as client:
        res = await client.get("/static/tokens.css")

    assert res.status_code == 200
    assert "text/css" in res.headers["content-type"]


@pytest.mark.anyio
async def test_tokens_define_the_shared_custom_properties(cms: CMS) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=cms.app), base_url="http://test"
    ) as client:
        body = (await client.get("/static/tokens.css")).text

    # The floor that stops iOS zooming on focus, and the touch target size —
    # both load-bearing for ADR 022 rather than cosmetic.
    assert "--font-size-input: 16px" in body
    assert "--target-min:          44px" in body
    assert "@media (hover: hover) and (pointer: fine)" in body


@pytest.mark.anyio
async def test_unknown_static_file_is_not_found(cms: CMS) -> None:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=cms.app), base_url="http://test"
    ) as client:
        res = await client.get("/static/nope.css")

    assert res.status_code == 404
