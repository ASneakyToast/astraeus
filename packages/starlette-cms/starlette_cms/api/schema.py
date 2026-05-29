"""Schema introspection endpoints — /api/schema"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.routing import Route

if TYPE_CHECKING:
    from starlette_cms.app import CMS


def make_schema_routes(cms: "CMS") -> list[Route]:
    # TODO: implement schema introspection endpoints
    return []
