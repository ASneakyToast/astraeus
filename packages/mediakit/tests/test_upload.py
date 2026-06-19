"""HTTP tests for the upload prepare + confirm endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

AUTH = {"Authorization": "Bearer test-secret"}


# ---------------------------------------------------------------------------
# POST /upload/prepare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prepare_upload_success(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/prepare",
        json={"filename": "photo.webp", "content_type": "image/webp", "size": 204800},
        headers=AUTH,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "upload_url" in data
    assert "key" in data
    assert "expires_at" in data
    assert data["key"].startswith("originals/")
    assert "photo.webp" in data["key"]


@pytest.mark.asyncio
async def test_prepare_upload_unauthorized(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/prepare",
        json={"filename": "photo.webp", "content_type": "image/webp", "size": 100},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_prepare_upload_missing_fields(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/prepare",
        json={"filename": "photo.webp"},
        headers=AUTH,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_prepare_upload_invalid_json(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/prepare",
        content=b"not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /upload/confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_upload_success(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/confirm",
        json={
            "key": "originals/abc12345/photo.webp",
            "filename": "photo.webp",
            "content_type": "image/webp",
            "size": 102400,
        },
        headers=AUTH,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["key"] == "originals/abc12345/photo.webp"
    assert data["content_type"] == "image/webp"


@pytest.mark.asyncio
async def test_confirm_upload_with_dimensions(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/confirm",
        json={
            "key": "originals/dim/photo.webp",
            "filename": "photo.webp",
            "content_type": "image/webp",
            "size": 50000,
            "width": 1920,
            "height": 1080,
        },
        headers=AUTH,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["width"] == 1920
    assert data["height"] == 1080


@pytest.mark.asyncio
async def test_confirm_upload_not_in_bucket(client: AsyncClient, mk) -> None:
    """If the key is 'deleted' from FakeStorage, confirm should 404."""
    mk.storage.remove("originals/gone/photo.webp")  # type: ignore[attr-defined]
    resp = await client.post(
        "/upload/confirm",
        json={
            "key": "originals/gone/photo.webp",
            "filename": "photo.webp",
            "content_type": "image/webp",
            "size": 100,
        },
        headers=AUTH,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_confirm_upload_unauthorized(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/confirm",
        json={
            "key": "originals/abc/photo.webp",
            "filename": "photo.webp",
            "content_type": "image/webp",
            "size": 100,
        },
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_confirm_upload_missing_fields(client: AsyncClient) -> None:
    resp = await client.post(
        "/upload/confirm",
        json={"key": "originals/abc/photo.webp"},
        headers=AUTH,
    )
    assert resp.status_code == 422
