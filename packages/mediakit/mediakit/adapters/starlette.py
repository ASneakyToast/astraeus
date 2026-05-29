"""Starlette adapter — create_media_mount()"""

from __future__ import annotations

from contextlib import asynccontextmanager

from starlette.applications import Starlette

from mediakit.catalog import Catalog
from mediakit.config import MediakitConfig
from mediakit.storage.s3_compatible import S3CompatibleBackend


def create_media_mount(
    bucket: str,
    *,
    endpoint_url: str | None = None,
    catalog_path: str = "./media_catalog.db",
    auth=None,
    **kwargs,
) -> Starlette:
    """
    Returns a Starlette ASGI app suitable for mounting at any path.

    Exposes lifespan_context(app) for composition with other plugin lifespans::

        @asynccontextmanager
        async def lifespan(app):
            async with cms.lifespan_context(app):
                async with media.lifespan_context(app):
                    yield
    """
    config = MediakitConfig(
        bucket=bucket,
        endpoint_url=endpoint_url,
        catalog_path=catalog_path,
        auth=auth,
        **kwargs,
    )

    @asynccontextmanager
    async def lifespan(app):
        app.state.storage = S3CompatibleBackend(config)
        app.state.catalog = Catalog(config.catalog_path)
        await app.state.catalog.initialize()
        app.state.config = config
        yield
        await app.state.catalog.close()

    # TODO: wire up routes
    app = Starlette(routes=[], lifespan=lifespan)
    app.lifespan_context = lifespan  # expose for external composition
    return app
