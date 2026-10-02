"""
Gateway admin API endpoints — registered on the CMS via extension routes.

Routes added to the CMS:
  GET  /api/gateways                        — list all installed gateways
  GET  /api/gateways/{name}                 — metadata for one gateway
  POST /api/gateways/{name}/sync            — kick off an async sync job
  GET  /api/gateways/{name}/sync/{run_id}   — poll job status / result

State, for workers outside the CMS process (CLI, MCP sidecars) — see
:class:`~starlette_cms_gateways.state.RemoteSyncState`:
  GET/PUT /api/gateways/{name}/cursor       — the sync cursor
  POST    /api/gateways/{name}/runs         — open a job record
  PATCH   /api/gateways/{name}/runs/{id}    — close it

All routes except the job poll require the CMS's write auth (API key or session).

Design notes:

- Sync state (job records and the cursor) lives in the CMS's own
  SQLite file by default (``GatewayAdmin(jobs_db_path=...)`` overrides) — the one
  file that is persistent and backed up.  The tables sit beside the CMS's and stay
  out of the block registry and the editor UI.  Only this process opens the file;
  other workers use the routes above, so there is one cursor, not one per process.
- Sync tasks run as ``asyncio.Task`` objects (fire-and-forget on POST).
- The CMSClient used inside each sync task routes through the CMS ASGI app
  in-process via ``httpx.ASGITransport`` — no host URL or open port is needed.
- Gateway discovery uses :func:`~starlette_cms_gateways.discovery.discover_gateways`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import httpx
import structlog
from httpx import ASGITransport
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from starlette_cms_gateways.base import SyncRange
from starlette_cms_gateways.client import CMSClient
from starlette_cms_gateways.discovery import discover_gateways
from starlette_cms_gateways.runner import run_recorded

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
            cursor_dt = await jobs.get_cursor(name)
            items.append(
                {
                    "name": name,
                    "service_name": getattr(cls, "service_name", None),
                    "block_type": getattr(cls, "block_type", None),
                    "auto_publish": getattr(cls, "auto_publish", False),
                    "immutable": getattr(cls, "immutable", False),
                    "last_synced": last_synced_dt.isoformat() if last_synced_dt else None,
                    "cursor": cursor_dt.isoformat() if cursor_dt else None,
                    "default_range": getattr(cls, "default_range", "since_last_sync"),
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
                "default_range": getattr(cls, "default_range", "since_last_sync"),
                "cursor": (c.isoformat() if (c := await jobs.get_cursor(name)) else None),
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

        # Optional JSON body: {"range": "since_last_sync" | "all_time" | "custom",
        #                      "from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
        try:
            payload = await request.json() if await request.body() else {}
            sync_range = SyncRange.parse(
                payload.get("range"),
                payload.get("from"),
                payload.get("to"),
                default=getattr(cls, "default_range", "since_last_sync"),
            )
        except (ValueError, TypeError, AttributeError) as exc:
            return JSONResponse({"error": f"Invalid sync range: {exc}"}, status_code=422)

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
                result = await run_recorded(gateway, jobs, name, sync_range, run_id=run_id)
                logger.info(
                    "starlette_cms_gateways.admin.sync_done",
                    gateway=name,
                    run_id=run_id,
                    created=result.created,
                    updated=result.updated,
                    skipped=result.skipped,
                    deferred=len(result.deferred),
                    errors=len(result.errors),
                )
            except Exception as exc:  # noqa: BLE001
                # run_recorded has already marked the job as an error.
                logger.error(
                    "starlette_cms_gateways.admin.sync_error",
                    gateway=name,
                    run_id=run_id,
                    error=str(exc),
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
    # Sync state: cursor and job records (for workers outside the CMS)
    # ------------------------------------------------------------------

    async def _state_request(request: Request) -> tuple[str, dict, JSONResponse | None]:
        """Auth, the gateway name, and the JSON body (``{}`` when there is none)."""
        if (err := await _check_auth(request)) is not None:
            return "", {}, err
        name = request.path_params["name"]
        gateways = discover_gateways()
        if name not in gateways:
            return (
                name,
                {},
                JSONResponse(
                    {"error": f"Gateway {name!r} not found.", "available": sorted(gateways)},
                    status_code=404,
                ),
            )
        if request.method in ("PUT", "POST", "PATCH"):
            try:
                body = await request.json() if await request.body() else {}
            except ValueError:
                return name, {}, JSONResponse({"error": "Invalid JSON body"}, status_code=400)
            if not isinstance(body, dict):
                return name, {}, JSONResponse({"error": "Body must be an object"}, status_code=400)
            return name, body, None
        return name, {}, None

    async def cursor_endpoint(request: Request) -> JSONResponse:
        """``GET`` the gateway's sync cursor; ``PUT {"cursor": ISO8601}`` to set it."""
        name, body, err = await _state_request(request)
        if err is not None:
            return err
        if request.method == "PUT":
            try:
                cursor = datetime.fromisoformat(str(body["cursor"]))
            except (KeyError, ValueError):
                return JSONResponse(
                    {"error": "Body must be {\"cursor\": <ISO 8601 datetime>}"}, status_code=422
                )
            await jobs.set_cursor(name, cursor)
        current = await jobs.get_cursor(name)
        return JSONResponse({"gateway": name, "cursor": current.isoformat() if current else None})

    async def create_run(request: Request) -> JSONResponse:
        """Open a job record for a run a worker is about to make."""
        name, body, err = await _state_request(request)
        if err is not None:
            return err
        run_id = str(body.get("run_id") or uuid.uuid4())
        await jobs.create(run_id, name)
        return JSONResponse({"run_id": run_id, "gateway_name": name, "status": "running"}, 201)

    async def finish_run(request: Request) -> JSONResponse:
        """Close a job record: ``{"status": "done"|"error", "created": n, ...}``."""
        name, body, err = await _state_request(request)
        if err is not None:
            return err
        run_id = request.path_params["run_id"]
        job = await jobs.get(run_id)
        if job is None or job.get("gateway_name") != name:
            return JSONResponse({"error": f"Job {run_id!r} not found."}, status_code=404)
        status = body.get("status")
        if status not in ("done", "error"):
            return JSONResponse({"error": "status must be 'done' or 'error'"}, status_code=422)
        try:
            await jobs.finish(
                run_id,
                status=status,
                created=int(body.get("created", 0)),
                updated=int(body.get("updated", 0)),
                skipped=int(body.get("skipped", 0)),
                errors=body.get("errors") or [],
                error=str(body.get("error", "")),
                deferred=body.get("deferred") or [],
                range=body.get("range") or None,
            )
        except (TypeError, ValueError) as exc:
            return JSONResponse({"error": f"Invalid job result: {exc}"}, status_code=422)
        return JSONResponse(await jobs.get(run_id))

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
        Route(
            "/api/gateways/{name}/cursor",
            endpoint=cursor_endpoint,
            methods=["GET", "PUT"],
            name="gateway_cursor",
        ),
        Route(
            "/api/gateways/{name}/runs",
            endpoint=create_run,
            methods=["POST"],
            name="gateway_run_create",
        ),
        Route(
            "/api/gateways/{name}/runs/{run_id}",
            endpoint=finish_run,
            methods=["PATCH"],
            name="gateway_run_finish",
        ),
    ]
