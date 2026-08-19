"""
Gateway admin API endpoints — registered on the CMS via extension routes.

Routes added to the CMS:
  GET  /api/gateways                        — list all installed gateways
  GET  /api/gateways/{name}                 — metadata for one gateway
  POST /api/gateways/{name}/sync            — kick off an async sync job
  GET  /api/gateways/{name}/sync/{run_id}   — poll job status / result

All mutating routes require ``Authorization: Bearer <api_key>``.

Design notes:

- Sync job records are stored in a dedicated SQLite database (``gateway_jobs.db``
  by default, configurable via ``GatewayAdmin(jobs_db_path=...)``) — separate
  from the CMS content database.  This keeps operational state out of the block
  registry and the editor UI.
- Sync tasks run as ``asyncio.Task`` objects (fire-and-forget on POST).
- The CMSClient used inside each sync task routes through the CMS ASGI app
  in-process via ``httpx.ASGITransport`` — no host URL or open port is needed.
- Gateway discovery uses :func:`~starlette_cms_gateways.discovery.discover_gateways`.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING

import httpx
import structlog
from httpx import ASGITransport
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from starlette_cms_gateways.client import CMSClient
from starlette_cms_gateways.discovery import discover_gateways

if TYPE_CHECKING:
    from starlette_cms.app import CMS

    from starlette_cms_gateways.admin.app import GatewayAdmin
    from starlette_cms_gateways.jobstore import JobStore

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# CMS client factory
# ---------------------------------------------------------------------------


def _build_cms_client(cms: CMS) -> CMSClient:
    """
    Build a :class:`~starlette_cms_gateways.client.CMSClient` that routes
    HTTP calls through the CMS ASGI app in-process via ``ASGITransport``.
    """
    from starlette.applications import Starlette
    from starlette.routing import Mount

    root_app = Starlette(routes=[Mount(cms.mount_path, app=cms.app)])
    transport = ASGITransport(app=root_app)
    http = httpx.AsyncClient(transport=transport, base_url="http://localhost")
    return CMSClient(
        base_url=f"http://localhost{cms.mount_path}",
        api_key=cms.api_key,
        _http_client=http,
    )


# ---------------------------------------------------------------------------
# Route factories
# ---------------------------------------------------------------------------


def make_gateway_api_routes(admin: GatewayAdmin) -> list[Route]:
    """
    Return the CMS extension routes for the gateway admin API.

    All routes close over *admin* to share its CMS reference and job store.
    """
    cms = admin.cms
    jobs: JobStore = admin.jobs

    async def _check_auth(request: Request) -> JSONResponse | None:
        from starlette_cms.auth import require_auth

        return await require_auth(request, cms)

    # ------------------------------------------------------------------
    # GET /api/gateways
    # ------------------------------------------------------------------

    async def list_gateways(request: Request) -> JSONResponse:
        """List all gateways discovered via entry points."""
        if (err := await _check_auth(request)) is not None:
            return err

        gateways = discover_gateways()
        items = []
        for name, cls in sorted(gateways.items()):
            # PERF: consider bulk GROUP BY query if N grows large
            last_synced_dt = await jobs.get_last_synced(name)
            items.append(
                {
                    "name": name,
                    "service_name": getattr(cls, "service_name", None),
                    "block_type": getattr(cls, "block_type", None),
                    "auto_publish": getattr(cls, "auto_publish", False),
                    "immutable": getattr(cls, "immutable", False),
                    "last_synced": last_synced_dt.isoformat() if last_synced_dt else None,
                }
            )
        return JSONResponse({"gateways": items, "total": len(items)})

    # ------------------------------------------------------------------
    # GET /api/gateways/{name}
    # ------------------------------------------------------------------

    async def get_gateway(request: Request) -> JSONResponse:
        """Return metadata for a single installed gateway, including recent jobs."""
        if (err := await _check_auth(request)) is not None:
            return err

        name = request.path_params["name"]
        gateways = discover_gateways()
        cls = gateways.get(name)
        if cls is None:
            return JSONResponse(
                {"error": f"Gateway {name!r} not found.", "available": sorted(gateways)},
                status_code=404,
            )

        recent = await jobs.list_for_gateway(name)
        return JSONResponse(
            {
                "name": name,
                "service_name": getattr(cls, "service_name", None),
                "block_type": getattr(cls, "block_type", None),
                "auto_publish": getattr(cls, "auto_publish", False),
                "immutable": getattr(cls, "immutable", False),
                "recent_jobs": recent,
            }
        )

    # ------------------------------------------------------------------
    # POST /api/gateways/{name}/sync
    # ------------------------------------------------------------------

    async def trigger_sync(request: Request) -> JSONResponse:
        """
        Kick off an async sync job for the named gateway.

        Returns 202 immediately with a ``run_id``.  Poll
        ``GET /api/gateways/{name}/sync/{run_id}`` for status.
        """
        if (err := await _check_auth(request)) is not None:
            return err

        name = request.path_params["name"]
        gateways = discover_gateways()
        cls = gateways.get(name)
        if cls is None:
            return JSONResponse(
                {"error": f"Gateway {name!r} not found.", "available": sorted(gateways)},
                status_code=404,
            )

        run_id = str(uuid.uuid4())
        await jobs.create(run_id, name)

        logger.info(
            "starlette_cms_gateways.admin.sync_triggered",
            gateway=name,
            run_id=run_id,
        )

        async def _run_sync() -> None:
            client = _build_cms_client(cms)
            try:
                gateway = cls(cms_client=client, job_store=jobs, job_store_key=name)
                result = await gateway.sync()
                await jobs.finish(
                    run_id,
                    status="done",
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                    errors=result.errors,
                )
                logger.info(
                    "starlette_cms_gateways.admin.sync_done",
                    gateway=name,
                    run_id=run_id,
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                    errors=len(result.errors),
                )
            except Exception as exc:  # noqa: BLE001
                await jobs.finish(
                    run_id,
                    status="error",
                    error=str(exc),
                )
                logger.error(
                    "starlette_cms_gateways.admin.sync_error",
                    gateway=name,
                    run_id=run_id,
                    exc_info=exc,
                )
            finally:
                await client.close()

        asyncio.create_task(_run_sync(), name=f"gateway_sync:{name}:{run_id}")

        return JSONResponse(
            {
                "run_id": run_id,
                "gateway_name": name,
                "status": "running",
                "poll_url": f"{cms.mount_path}/api/gateways/{name}/sync/{run_id}",
            },
            status_code=202,
        )

    # ------------------------------------------------------------------
    # GET /api/gateways/{name}/sync/{run_id}
    # ------------------------------------------------------------------

    async def get_sync_job(request: Request) -> JSONResponse:
        """Poll the status of a previously triggered sync job."""
        run_id = request.path_params["run_id"]
        job = await jobs.get(run_id)
        if job is None:
            return JSONResponse({"error": f"Job {run_id!r} not found."}, status_code=404)
        return JSONResponse(job)

    # ------------------------------------------------------------------
    # Route list
    # ------------------------------------------------------------------

    return [
        Route("/api/gateways", endpoint=list_gateways, methods=["GET"], name="gateways_list"),
        Route("/api/gateways/{name}", endpoint=get_gateway, methods=["GET"], name="gateway_detail"),
        Route(
            "/api/gateways/{name}/sync",
            endpoint=trigger_sync,
            methods=["POST"],
            name="gateway_trigger_sync",
        ),
        Route(
            "/api/gateways/{name}/sync/{run_id}",
            endpoint=get_sync_job,
            methods=["GET"],
            name="gateway_sync_job",
        ),
    ]
