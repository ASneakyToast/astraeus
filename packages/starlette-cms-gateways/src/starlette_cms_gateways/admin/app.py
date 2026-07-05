"""
GatewayAdmin — mountable Starlette sub-application for the gateway admin UI.

Extends starlette-cms at init time by:

1. Auto-registering a ``gateway_sync_job`` block type on the CMS — job records
   are stored as append-only CMS documents, surviving process restarts and
   appearing in the editor UI.
2. Registering four API routes on the CMS via
   :meth:`~starlette_cms.app.CMS.register_extension_route`.
3. Serving a shell page from its own sub-application.

Usage::

    from starlette_cms import CMS
    from starlette_cms_gateways.admin import GatewayAdmin
    from starlette.applications import Starlette
    from starlette.routing import Mount

    cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")
    admin = GatewayAdmin(cms=cms)

    app = Starlette(
        routes=[
            Mount("/cms", app=cms.app),
            Mount("/gateways", app=admin.app),
        ],
        lifespan=cms.lifespan,
    )

Shell:   GET  /gateways/shell
API:     GET  /cms/api/gateways
         GET  /cms/api/gateways/{name}
         POST /cms/api/gateways/{name}/sync
         GET  /cms/api/gateways/{name}/sync/{run_id}
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from starlette.applications import Starlette

if TYPE_CHECKING:
    from starlette_cms.app import CMS


class GatewayAdmin:
    """
    Mountable Starlette gateway admin sub-application.

    :param cms: The CMS instance to extend.  At init time this registers:

        * A ``gateway_sync_job`` append-only block type for persisting sync
          job records in the CMS database.
        * Four gateway API routes via
          :meth:`~starlette_cms.app.CMS.register_extension_route`.

        Must be called before the first access of ``cms.app``.

    :param mount_path: The path this admin UI is mounted at (used for shell
        links and the ``poll_url`` in sync responses).  Defaults to
        ``"/gateways"``.
    :param auth: Optional auth callable ``(request) -> bool`` protecting the
        ``/shell`` HTML page.  API routes always use the CMS auth model
        (``Authorization: Bearer <api_key>``).  Defaults to ``None`` (shell
        is open) — set this when the admin is exposed on a public server.
    """

    def __init__(
        self,
        *,
        cms: CMS,
        mount_path: str = "/gateways",
        auth: Callable | None = None,
    ) -> None:
        self.cms = cms
        self.mount_path = mount_path
        self.auth = auth

        # Register the gateway_sync_job block type so job records persist in
        # the CMS database across process restarts.
        from starlette_cms_gateways.admin.api import register_sync_job_block

        register_sync_job_block(cms)

        # Register the four gateway API routes on the CMS.
        # Must happen before cms.app is accessed.
        from starlette_cms_gateways.admin.api import make_gateway_api_routes

        for route in make_gateway_api_routes(self):
            cms.register_extension_route(
                path=route.path,
                endpoint=route.endpoint,
                methods=list(route.methods or []),
                name=route.name or route.path.replace("/", "_").strip("_"),
            )

        self._app: Starlette | None = None

    @property
    def app(self) -> Starlette:
        """Build and return the Starlette sub-application. Built once on first access."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        from starlette_cms_gateways.admin.routes import make_admin_routes

        return Starlette(routes=make_admin_routes(self))
