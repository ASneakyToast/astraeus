"""Upload flow routes — presigned PUT preparation and post-upload confirmation.

Two-step flow:

1. Client POSTs ``/upload/prepare`` → receives a presigned PUT URL.
2. Client PUTs the file directly to the bucket (no bytes through this server).
3. Client POSTs ``/upload/confirm`` → mediakit verifies object exists,
   inserts into catalog, returns asset metadata.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from mediakit.app import MediaKit


def _make_key(filename: str, content_type: str, timestamp: str) -> str:
    """Generate a content-addressed storage key.

    ``originals/{sha256_prefix8}/{filename}``

    The prefix is the first 8 hex chars of SHA-256(filename + content_type + timestamp).
    This is deterministic enough for deduplication without needing the actual bytes.
    """
    raw = filename + content_type + timestamp
    prefix = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"originals/{prefix}/{filename}"


def make_upload_routes(mk: MediaKit) -> list[Route]:
    """Return the upload route list for *mk*."""

    async def prepare(request: Request) -> JSONResponse:
        """``POST /upload/prepare`` — generate a presigned PUT URL."""
        from mediakit.auth import require_auth

        if (err := await require_auth(request, mk)) is not None:
            return err

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        filename = body.get("filename")
        content_type = body.get("content_type")
        size = body.get("size")

        if not filename or not content_type or size is None:
            return JSONResponse(
                {"error": "filename, content_type, and size are required"},
                status_code=422,
            )

        from datetime import UTC, datetime

        timestamp = datetime.now(UTC).isoformat()
        key = _make_key(str(filename), str(content_type), timestamp)

        result = await mk.storage.prepare_upload(key, str(content_type), mk.config.upload_expires)
        return JSONResponse(result)

    async def confirm(request: Request) -> JSONResponse:
        """``POST /upload/confirm`` — verify upload, insert into catalog, return asset."""
        from mediakit.auth import require_auth

        if (err := await require_auth(request, mk)) is not None:
            return err

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        key = body.get("key")
        filename = body.get("filename")
        content_type = body.get("content_type")
        size = body.get("size")

        if not key or not filename or not content_type or size is None:
            return JSONResponse(
                {"error": "key, filename, content_type, and size are required"},
                status_code=422,
            )

        exists = await mk.storage.confirm_exists(str(key))
        if not exists:
            return JSONResponse(
                {"error": "Object not found in bucket — upload may not have completed"},
                status_code=404,
            )

        # Use a placeholder hash (first 16 chars of key name) since we don't have the bytes
        content_hash = hashlib.sha256(str(key).encode()).hexdigest()[:16]

        asset = await mk.catalog.insert_asset(
            key=str(key),
            content_hash=content_hash,
            bucket=mk.config.bucket,
            filename=str(filename),
            content_type=str(content_type),
            size=int(size),
            width=body.get("width"),
            height=body.get("height"),
        )
        return JSONResponse(asset, status_code=201)

    return [
        Route("/upload/prepare", endpoint=prepare, methods=["POST"]),
        Route("/upload/confirm", endpoint=confirm, methods=["POST"]),
    ]
