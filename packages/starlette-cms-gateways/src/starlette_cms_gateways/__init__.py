"""
starlette-cms-gateways — Gateway framework for starlette-cms.

Pull data from external services into your CMS as documents, with
deduplication and CLI tooling built in.

Quickstart::

    from starlette_cms_gateways import BaseGateway, GatewayItem
    from collections.abc import AsyncIterator

    class MyGateway(BaseGateway):
        service_name = "my_service"
        block_type   = "my_item"

        async def fetch(self) -> AsyncIterator[GatewayItem]:
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

import logging as _logging

from starlette_cms_gateways.base import BaseGateway, GatewayItem, SyncResult

# Library contract: install NullHandler so the host app controls log routing.
# See ADR 017.
_logging.getLogger("starlette_cms_gateways").addHandler(_logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "BaseGateway",
    "GatewayItem",
    "JobStore",
    "SyncResult",
    "GatewayAdmin",
]


def __getattr__(name: str):
    # Lazy import to avoid pulling in Starlette deps at import time for
    # consumers that only use the gateway base types.
    if name == "GatewayAdmin":
        from starlette_cms_gateways.admin import GatewayAdmin as _GatewayAdmin

        return _GatewayAdmin
    if name == "JobStore":
        from starlette_cms_gateways.jobstore import JobStore as _JobStore

        return _JobStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
