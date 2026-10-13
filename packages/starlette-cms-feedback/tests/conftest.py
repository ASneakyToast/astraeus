"""Shared fixtures: a real in-process CMS with FeedbackAdmin mounted beside it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from httpx import ASGITransport
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette_cms import CMS
from starlette_cms_feedback import FeedbackAdmin

API_KEY = "test-secret"


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest_asyncio.fixture
async def feedback_app(tmp_path: Path) -> AsyncIterator[dict[str, Any]]:
    """
    Yields a dict with ``client`` (routed through the full Starlette app),
    ``root`` (the ASGI app, for tests that build their own client), ``cms``
    and ``admin``.
    """
    cms = CMS(
        database_url=f"sqlite:///{tmp_path / 'content.db'}",
        auth="apikey",
        api_key=API_KEY,
        mount_path="/cms",
    )
    admin = FeedbackAdmin(cms=cms, db_path=tmp_path / "feedback.db")
    root = Starlette(
        routes=[
            Mount("/cms", app=cms.app),
            Mount("/feedback", app=admin.app),
        ]
    )

    async with cms.lifespan_context(None):
        client = httpx.AsyncClient(transport=ASGITransport(app=root), base_url="http://testserver")
        try:
            yield {"admin": admin, "client": client, "cms": cms, "root": root}
        finally:
            await client.aclose()
