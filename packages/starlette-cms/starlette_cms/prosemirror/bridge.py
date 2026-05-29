"""ProseMirror bridge — generates ProseMirror schema from the block registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette_cms.registry import BlockRegistry


class ProseMirrorBridge:
    """
    Generates a ProseMirror-compatible schema definition from the block registry.
    Activated by starlette-editor at init time.
    """

    def __init__(self, registry: BlockRegistry) -> None:
        self.registry = registry

    def generate_schema(self) -> dict:
        """Return the ProseMirror schema definition for all registered blocks."""
        # TODO: implement schema generation
        return {"nodes": {}, "marks": {}}

    async def schema_endpoint(self, request: Request) -> JSONResponse:
        """Serves as the /api/editor-schema endpoint, registered via extension routes."""
        return JSONResponse(self.generate_schema())
