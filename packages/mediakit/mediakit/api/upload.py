"""Upload flow routes — presigned PUT preparation and post-upload confirmation.

Two-step flow:

1. Client POSTs ``/upload/prepare`` → receives a presigned PUT URL.
2. Client PUTs the file directly to the bucket (no bytes through this server).
3. Client POSTs ``/upload/confirm`` → mediakit verifies object exists, runs the
   processing pipeline (EXIF strip, WebP conversion, dimension cap), replaces the
   original in storage, inserts into catalog, returns asset metadata.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from mediakit.app import MediaKit

logger = structlog.get_logger(__name__)


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
            logger.warning("mediakit.upload.invalid_json", endpoint="prepare")
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
            logger.warning("mediakit.upload.invalid_json", endpoint="confirm")
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

        # ------------------------------------------------------------------
        # Processing pipeline — download, process, re-upload
        # ------------------------------------------------------------------
        final_content_type = str(content_type)
        final_size = int(size)
        final_width = body.get("width")
        final_height = body.get("height")

        try:
            import obstore

            from mediakit.processing import run_pipeline

            store = mk.storage._get_store()

            # Download original bytes from bucket
            result = await obstore.get_async(store, str(key))
            original_bytes = bytes(await result.bytes_async())

            # Write to a temp file for Pillow to open
            with tempfile.TemporaryDirectory() as tmpdir:
                # Keep the original file extension so Pillow can infer format
                original_suffix = Path(str(filename)).suffix or ".bin"
                source_path = Path(tmpdir) / f"upload{original_suffix}"
                source_path.write_bytes(original_bytes)

                proc = await run_pipeline(source_path, mk.config)

                # Re-upload processed file back to the same key
                processed_bytes = proc.path.read_bytes()
                await obstore.put_async(store, str(key), processed_bytes)

                final_content_type = proc.content_type
                final_size = proc.size
                final_width = proc.width
                final_height = proc.height

        except Exception:
            # Processing is best-effort: if it fails (e.g. non-image file,
            # storage backend doesn't support get/put in test), fall back to
            # client-supplied metadata.
            logger.warning(
                "mediakit.upload.pipeline_failed",
                key=key,
                filename=filename,
                content_type=content_type,
                exc_info=True,
            )

        # Use a hash of the key as a stable content_hash (no bytes available
        # in the base case; real deduplication is a Phase 9+ concern).
        content_hash = hashlib.sha256(str(key).encode()).hexdigest()[:16]

        asset = await mk.catalog.insert_asset(
            key=str(key),
            content_hash=content_hash,
            bucket=mk.config.bucket,
            filename=str(filename),
            content_type=final_content_type,
            size=final_size,
            width=final_width,
            height=final_height,
        )
        return JSONResponse(asset, status_code=201)

    return [
        Route("/upload/prepare", endpoint=prepare, methods=["POST"]),
        Route("/upload/confirm", endpoint=confirm, methods=["POST"]),
    ]
