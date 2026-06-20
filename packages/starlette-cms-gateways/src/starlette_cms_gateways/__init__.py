"""
starlette-cms-gateways — Gateway framework for starlette-cms.

Pull data from external services into your CMS as documents, with
deduplication, incremental sync, and CLI tooling built in.

Quickstart::

    from starlette_cms_gateways import BaseGateway, GatewayItem
    from collections.abc import AsyncIterator
    from datetime import datetime

    class MyGateway(BaseGateway):
        service_name = "my_service"
        block_type   = "my_item"
        auto_publish = True

        async def fetch(self, since: datetime | None) -> AsyncIterator[GatewayItem]:
            yield GatewayItem(
                import_ref="my_service:item:abc123",
                slug="my-item-abc123",
                body={"title": "Hello"},
            )

Register as an entry point in pyproject.toml::

    [project.entry-points."starlette_cms_gateways.gateways"]
    my-gateway = "myapp.gateways:MyGateway"

Then sync::

    gateways sync my-gateway --cms-url https://cms.example.com --api-key $KEY
"""

from __future__ import annotations

from starlette_cms_gateways.base import BaseGateway, GatewayItem, SyncResult

__version__ = "0.1.0"

__all__ = [
    "BaseGateway",
    "GatewayItem",
    "SyncResult",
]
