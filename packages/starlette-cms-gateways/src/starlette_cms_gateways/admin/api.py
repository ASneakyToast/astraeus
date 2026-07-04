"""
Gateway admin API endpoints — registered on the CMS via extension routes.

Routes added to the CMS:
  GET  /api/gateways                        — list all installed gateways
  GET  /api/gateways/{name}                 — metadata for one gateway
  POST /api/gateways/{name}/sync            — kick off an async sync job
  GET  /api/gateways/{name}/sync/{run_id}   — poll job status / result

All mutating routes require ``Authorization: Bearer <api_key>``.

Design notes:

- Sync jobs run as ``asyncio.Task`` objects, stored in an in-memory dict keyed
  by a UUID run_id on the :class:`GatewayAdmin` instance.  No external queue.
- The CMSClient used by each sync job routes through the CMS ASGI app in-process
  via ``httpx.ASGITransport`` — no host URL or open port is needed.
- Gateway discovery uses the canonical
  ``importlib.metadata.entry_points(group="starlette_cms_gateways.gateways")``
  path, same as the CLI.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from httpx import ASGITransport
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from starlette_cms_gateways.base import SyncResult
from starlette_cms_gateways.cli import _discover_gateways
from starlette_cms_gateways.client import CMSClient, CMSError

if TYPE_CHECKING:
    from starlette_cms_gateways.admin.app import GatewayAdmin

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Job state container
# ---------------------------------------------------------------------------


class _SyncJob:
    """
    In-memory record for a single async sync job.

    :param run_id: UUID assigned at job creation.
    :param gateway_name: Entry-point name of the gateway being synced.
    :param started_at: UTC timestamp when the job was enqueued.
    """

    def __init__(self, run_id: str, gateway_name: str) -> None:
        self.run_id = run_id
        self.gateway_name = gateway_name
        self.status: str = "running"  # "running" | "done" | "error"
        self.started_at: str = datetime.now(UTC).isoformat()
        self.finished_at: str | None = None
        self.result: SyncResult | None = None
        self.error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "run_id": self.run_id,
            "gateway_name": self.gateway_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.result is not None:
            out["result"] = self.result.to_dict()
        if self.error is not None:
            out["error"] = self.error
        return out


# ---------------------------------------------------------------------------
# Route factories
# ---------------------------------------------------------------------------


def make_gateway_api_routes(admin: GatewayAdmin) -> list[Route]:
    """
    Return the CMS extension routes for the gateway admin API.

    All routes close over *admin* so they share its job registry and CMS ref.
    """
    cms = admin.cms

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _check_auth(request: Request) -> JSONResponse | None:
        """Return 401 on auth failure, None on success."""
        from starlette_cms.auth import require_auth

        return await require_auth(request, cms)

    def _build_cms_client() -> CMSClient:
        """
        Build a CMSClient that routes HTTP calls through the CMS ASGI app
        in-process.  Lazily constructed on each call so cms.app is already
        frozen before the first sync request arrives.
        """
        from starlette.applications import Starlette
        from starlette.routing import Mount

        # Wrap the CMS sub-app in a full Starlette app so ASGITransport's
        # root handler sees the right path prefix.
        root_app = Starlette(routes=[Mount(cms.mount_path, app=cms.app)])
        transport = ASGITransport(app=root_app)
        http = httpx.AsyncClient(transport=transport, base_url="http://localhost")
        return CMSClient(
            base_url=f"http://localhost{cms.mount_path}",
            api_key=cms.api_key,
            _http_client=http,
        )

    # ------------------------------------------------------------------
    # GET /api/gateways
    # ------------------------------------------------------------------

    async def list_gateways(request: Request) -> JSONResponse:
        """List all gateways discovered via entry points."""
        gateways = _discover_gateways()
        items = []
        for name, cls in sorted(gateways.items()):
            items.append(
                {
                    "name": name,
                    "service_name": getattr(cls, "service_name", None),
                    "block_type": getattr(cls, "block_type", None),
                    "auto_publish": getattr(cls, "auto_publish", False),
                    "immutable": getattr(cls, "immutable", False),
                }
            )
        return JSONResponse({"gateways": items, "total": len(items)})

    # ------------------------------------------------------------------
    # GET /api/gateways/{name}
    # ------------------------------------------------------------------

    async def get_gateway(request: Request) -> JSONResponse:
        """Return metadata for a single installed gateway."""
        name = request.path_params["name"]
        gateways = _discover_gateways()
        cls = gateways.get(name)
        if cls is None:
            available = sorted(gateways)
            return JSONResponse(
                {"error": f"Gateway {name!r} not found.", "available": available},
                status_code=404,
            )
        # Include recent jobs for this gateway
        recent_jobs = [j.to_dict() for j in admin._jobs.values() if j.gateway_name == name]
        recent_jobs.sort(key=lambda j: j["started_at"], reverse=True)
        return JSONResponse(
            {
                "name": name,
                "service_name": getattr(cls, "service_name", None),
                "block_type": getattr(cls, "block_type", None),
                "auto_publish": getattr(cls, "auto_publish", False),
                "immutable": getattr(cls, "immutable", False),
                "recent_jobs": recent_jobs[:10],
            }
        )

    # ------------------------------------------------------------------
    # POST /api/gateways/{name}/sync
    # ------------------------------------------------------------------

    async def trigger_sync(request: Request) -> JSONResponse:
        """
        Kick off an async sync job for the named gateway.

        Returns 202 immediately with a ``run_id`` to poll.
        """
        if (err := await _check_auth(request)) is not None:
            return err

        name = request.path_params["name"]
        gateways = _discover_gateways()
        cls = gateways.get(name)
        if cls is None:
            available = sorted(gateways)
            return JSONResponse(
                {"error": f"Gateway {name!r} not found.", "available": available},
                status_code=404,
            )

        run_id = str(uuid.uuid4())
        job = _SyncJob(run_id=run_id, gateway_name=name)
        admin._jobs[run_id] = job

        logger.info(
            "starlette_cms_gateways.admin.sync_triggered",
            gateway=name,
            run_id=run_id,
        )

        async def _run_sync() -> None:
            client = _build_cms_client()
            try:
                gateway = cls(cms_client=client)
                result = await gateway.sync()
                job.status = "done"
                job.result = result
                job.finished_at = datetime.now(UTC).isoformat()
                logger.info(
                    "starlette_cms_gateways.admin.sync_done",
                    gateway=name,
                    run_id=run_id,
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                    errors=len(result.errors),
                )
            except CMSError as exc:
                job.status = "error"
                job.error = str(exc)
                job.finished_at = datetime.now(UTC).isoformat()
                logger.error(
                    "starlette_cms_gateways.admin.sync_failed",
                    gateway=name,
                    run_id=run_id,
                    error=str(exc),
                )
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.error = f"Unexpected error: {exc}"
                job.finished_at = datetime.now(UTC).isoformat()
                logger.error(
                    "starlette_cms_gateways.admin.sync_error",
                    gateway=name,
                    run_id=run_id,
                    exc_info=exc,
                )
            finally:
                await client.close()

        # Fire and forget — the task outlives this request
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
        job = admin._jobs.get(run_id)
        if job is None:
            return JSONResponse(
                {"error": f"Job {run_id!r} not found."},
                status_code=404,
            )
        return JSONResponse(job.to_dict())

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
