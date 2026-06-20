"""
Editor — the starlette-editor plugin entry point.

Extends starlette-cms at init time by registering /api/editor-schema
via the CMS extension route mechanism.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette_cms.prosemirror import ProseMirrorBridge

if TYPE_CHECKING:
    from starlette_cms.app import CMS

import pathlib

STATIC_DIR = pathlib.Path(__file__).parent / "static"


class Editor:
    """
    Mountable Starlette editor sub-application.

    :param cms: The CMS instance to extend. Extension routes are registered at init time.
    :param media_base: Mount path of Mediakit — enables the image picker in ImageField editing.
    :param mount_path: The path this editor is mounted at.
    :param auth: Optional auth callable (request) -> bool protecting /shell.
    """

    def __init__(
        self,
        *,
        cms: CMS,
        media_base: str | None = None,
        mount_path: str = "/editor",
        auth: Callable | None = None,
    ) -> None:
        self.cms = cms
        self.media_base = media_base
        self.mount_path = mount_path
        self.auth = auth

        # Activate ProseMirror bridge and register /api/editor-schema on the CMS
        self.bridge = ProseMirrorBridge(cms.registry)
        cms.register_extension_route(
            path="/api/editor-schema",
            endpoint=self.bridge.schema_endpoint,
            methods=["GET"],
            name="editor_schema",
        )

        self._app: Starlette | None = None

    @property
    def app(self) -> Starlette:
        """Build and return the Starlette sub-application. Built once on first access."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        from starlette_editor.routes import make_editor_routes

        return Starlette(routes=make_editor_routes(self))
