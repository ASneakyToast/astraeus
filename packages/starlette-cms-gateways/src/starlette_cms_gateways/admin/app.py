"""
GatewayAdmin — mountable Starlette sub-application for the gateway admin UI.

Extends starlette-cms at init time by registering four API routes on the CMS
via :meth:`~starlette_cms.app.CMS.register_extension_route`, then serves a
shell page from its own sub-application.

Sync job records are stored in a dedicated SQLite database (separate from the
CMS content database) so they never appear in the block registry or editor UI.

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

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.applications import Starlette

from starlette_cms_gateways.jobstore import JobStore

if TYPE_CHECKING:
    from starlette_cms.app import CMS

DEFAULT_JOBS_DB = "gateway_jobs.db"


class GatewayAdmin:
    """
    Mountable Starlette gateway admin sub-application.

    :param cms: The CMS instance to extend.  Four gateway API routes are
        registered on it via
        :meth:`~starlette_cms.app.CMS.register_extension_route` at init time.
        Must be called before the first access of ``cms.app``.
    :param mount_path: The path this admin UI is mounted at.  Defaults to
        ``"/gateways"``.
    :param auth: Optional auth callable ``(request) -> bool`` protecting the
        ``/shell`` HTML page.  API routes always use the CMS auth model
        (``Authorization: Bearer <api_key>``).  Defaults to ``None`` — set
        this when the admin is exposed on a public server.
    :param jobs_db_path: Path to the SQLite database file used to persist sync
        job records.  Defaults to ``gateway_jobs.db`` in the current working
        directory.  Use an absolute path in production (e.g. next to the CMS
        database file).  Ignored if *job_store* is provided.
    :param job_store: A pre-built :class:`~starlette_cms_gateways.jobstore.JobStore`
        instance.  Use this to share a job store across multiple components or
        to control the database path explicitly.  When provided, *jobs_db_path*
        is ignored (a warning is emitted if a non-default path was also passed).
    """

    def __init__(
        self,
        *,
        cms: CMS,
        mount_path: str = "/gateways",
        auth: Callable | None = None,
        jobs_db_path: str | Path = DEFAULT_JOBS_DB,
        job_store: JobStore | None = None,
    ) -> None:
        self.cms = cms
        self.mount_path = mount_path
        self.auth = auth

        if job_store is not None:
            if jobs_db_path != DEFAULT_JOBS_DB:
                warnings.warn(
                    "jobs_db_path is ignored when job_store is provided",
                    stacklevel=2,
                )
            self.jobs = job_store
        else:
            self.jobs = JobStore(jobs_db_path)

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
