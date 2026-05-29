"""
mediakit — Media management for Starlette.

S3-compatible object storage, local SQLite catalog, IIIF Image API 3.0,
presigned upload flow, and an optional admin UI.

Quickstart::

    from mediakit.adapters.starlette import create_media_mount

    media = create_media_mount(
        bucket="my-bucket",
        endpoint_url="https://storage.googleapis.com",
        catalog_path="./media.db",
        auth=lambda request: request.user.is_authenticated,
    )

    # Mount in your Starlette app:
    # app.mount("/media", app=media)
"""

from mediakit.config import MediakitConfig

__version__ = "0.2.0"

__all__ = ["MediakitConfig"]
