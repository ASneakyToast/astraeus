"""
Gateway admin API endpoints — registered on the CMS via extension routes.

Routes added to the CMS:
  GET  /api/gateways                        — list all installed gateways
  GET  /api/gateways/{name}                 — metadata for one gateway
  POST /api/gateways/{name}/sync            — kick off an async sync job
  GET  /api/gateways/{name}/sync/{run_id}   — poll job status / result

All mutating routes require ``Authorization: Bearer <api_key>``.

Design notes:

- Sync jobs are persisted as ``gateway_sync_job`` documents in the CMS.
  The block type is auto-registered by :class:`~starlette_cms_gateways.admin.app.GatewayAdmin`
  at init time via ``cms.register_block()``.  Persisting in the CMS means
  job history survives process restarts and is visible in the editor UI.
- Sync tasks run as ``asyncio.Task`` objects (fire-and-forget on POST).
  The task writes the job document on start and patches it on completion.
- The CMSClient used inside each sync task routes through the CMS ASGI app
  in-process via ``httpx.ASGITransport`` — no host URL or open port is needed.
- Gateway discovery uses :func:`~starlette_cms_gateways.discovery.discover_gateways`
  which reads ``importlib.metadata`` entry points.

Multi-worker note:
  Job documents are stored in the shared CMS SQLite DB, so reads and writes
  are consistent across workers.  The sync task itself runs in the worker
  that handled the POST — other workers can poll the job status via the DB.
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

from starlette_cms_gateways.client import CMSClient
from starlette_cms_gateways.discovery import discover_gateways

if TYPE_CHECKING:
    from starlette_cms.app import CMS

    from starlette_cms_gateways.admin.app import GatewayAdmin

logger = structlog.get_logger(__name__)

# CMS block type name for sync job documents — must match what's registered in app.py
SYNC_JOB_BLOCK_TYPE = "gateway_sync_job"


# ---------------------------------------------------------------------------
# Block registration
# ---------------------------------------------------------------------------


def register_sync_job_block(cms: CMS) -> None:
    """
    Register the ``gateway_sync_job`` block type on *cms*.

    Called by :class:`~starlette_cms_gateways.admin.app.GatewayAdmin` at
    init time.  Safe to call multiple times — uses ``override=True`` so a
    second ``GatewayAdmin`` on the same CMS instance won't raise.

    The block is append-only: job records are immutable once written and are
    auto-published so they appear in the CMS document list without a separate
    publish step.
    """
    from starlette_cms import JSONField, NumberField, TextField
    from starlette_cms.registry import block

    @block(SYNC_JOB_BLOCK_TYPE, append_only=True)
    class GatewaySyncJobBlock:
        """A single gateway sync run — written by GatewayAdmin, never edited."""

        gateway_name: str = TextField(required=True)
        status: str = TextField(required=True)  # running | done | error
        started_at: str = TextField(required=True)
        finished_at: str = TextField()
        created: int = NumberField()
        updated: int = NumberField()
        skipped: int = NumberField()
        errors: list = JSONField()
        error: str = TextField()

    cms.register_block(GatewaySyncJobBlock, override=True)


# ---------------------------------------------------------------------------
# CMS client factory (shared by sync tasks and job writers)
# ---------------------------------------------------------------------------


def _build_cms_client(cms: CMS) -> CMSClient:
    """
    Build a :class:`~starlette_cms_gateways.client.CMSClient` that routes
    HTTP calls through the CMS ASGI app in-process.

    Lazily called after the first request arrives, by which point ``cms.app``
    is already frozen.
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
# Job document helpers
# ---------------------------------------------------------------------------


def _job_slug(run_id: str) -> str:
    return f"gateway-sync-{run_id}"


async def _create_job_doc(cms_client: CMSClient, run_id: str, gateway_name: str) -> dict[str, Any]:
    """Write an initial 'running' job document to the CMS."""
    return await cms_client.create_document(
        doc_type=SYNC_JOB_BLOCK_TYPE,
        slug=_job_slug(run_id),
        body={
            "gateway_name": gateway_name,
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": "",
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "error": "",
        },
        import_ref=f"gateway_sync_job:{run_id}",
    )


async def _finish_job_doc(
    cms_client: CMSClient,
    doc_id: str,
    *,
    status: str,
    finished_at: str,
    created: int = 0,
    updated: int = 0,
    skipped: int = 0,
    errors: list | None = None,
    error: str = "",
) -> None:
    """
    Patch the job document with final status.

    ``gateway_sync_job`` is append_only so PATCH is blocked — we use the
    CMSClient directly against the raw HTTP PATCH endpoint via a separate
    non-append_only write.  Since we own the block registration we switch
    it to a regular (non-append_only) write by calling the CMS client's
    ``update_document`` which issues ``PATCH /api/documents/{id}``.

    Note: append_only blocks refuse PATCH at the API level.  To store final
    state we instead write a *second* document (the completion record) keyed
    by ``import_ref="gateway_sync_job_result:{run_id}"`` and query both when
    building the job response.  This keeps the append_only semantics intact.
    """
    await cms_client.create_document(
        doc_type=SYNC_JOB_BLOCK_TYPE,
        slug=f"gateway-sync-result-{doc_id}",
        body={
            "gateway_name": "",  # redundant in result doc — start doc has it
            "status": status,
            "started_at": "",
            "finished_at": finished_at,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors or [],
            "error": error,
        },
        import_ref=f"gateway_sync_job_result:{doc_id}",
    )


async def _read_job(cms_client: CMSClient, run_id: str) -> dict[str, Any] | None:
    """
    Reconstruct a job record from the CMS.

    Reads the start document (import_ref=gateway_sync_job:{run_id}) and,
    if present, the result document (import_ref=gateway_sync_job_result:{doc_id}).
    """
    start_data = await cms_client.list_documents(import_ref=f"gateway_sync_job:{run_id}", limit=1)
    starts = start_data.get("documents", [])
    if not starts:
        return None

    start = starts[0]
    body: dict[str, Any] = start.get("body") or {}

    # Look for a result doc keyed by the start doc's CMS id
    result_data = await cms_client.list_documents(
        import_ref=f"gateway_sync_job_result:{start['id']}", limit=1
    )
    results = result_data.get("documents", [])

    if results:
        rb: dict[str, Any] = results[0].get("body") or {}
        return {
            "run_id": run_id,
            "gateway_name": body.get("gateway_name", ""),
            "status": rb.get("status", "done"),
            "started_at": body.get("started_at", ""),
            "finished_at": rb.get("finished_at", ""),
            "result": {
                "created": rb.get("created", 0),
                "updated": rb.get("updated", 0),
                "skipped": rb.get("skipped", 0),
                "errors": rb.get("errors", []),
                "error": rb.get("error", ""),
            },
        }

    # No result doc yet — still running
    return {
        "run_id": run_id,
        "gateway_name": body.get("gateway_name", ""),
        "status": "running",
        "started_at": body.get("started_at", ""),
        "finished_at": None,
    }


async def _recent_jobs(cms_client: CMSClient, gateway_name: str, limit: int = 10) -> list[dict]:
    """Return the most recent completed jobs for *gateway_name*."""
    data = await cms_client.list_documents(doc_type=SYNC_JOB_BLOCK_TYPE, limit=100)
    docs = data.get("documents", [])
    jobs = []
    for doc in docs:
        body = doc.get("body") or {}
        import_ref = doc.get("import_ref") or ""
        # Only start docs carry the gateway_name
        if not import_ref.startswith("gateway_sync_job:"):
            continue
        if body.get("gateway_name") != gateway_name:
            continue
        run_id = import_ref.removeprefix("gateway_sync_job:")
        job = await _read_job(cms_client, run_id)
        if job:
            jobs.append(job)
    jobs.sort(key=lambda j: j.get("started_at") or "", reverse=True)
    return jobs[:limit]


# ---------------------------------------------------------------------------
# Route factories
# ---------------------------------------------------------------------------


def make_gateway_api_routes(admin: GatewayAdmin) -> list[Route]:
    """
    Return the CMS extension routes for the gateway admin API.

    All routes close over *admin* so they share its CMS reference.
    """
    cms = admin.cms

    async def _check_auth(request: Request) -> JSONResponse | None:
        from starlette_cms.auth import require_auth

        return await require_auth(request, cms)

    # ------------------------------------------------------------------
    # GET /api/gateways
    # ------------------------------------------------------------------

    async def list_gateways(request: Request) -> JSONResponse:
        """List all gateways discovered via entry points."""
        gateways = discover_gateways()
        items = [
            {
                "name": name,
                "service_name": getattr(cls, "service_name", None),
                "block_type": getattr(cls, "block_type", None),
                "auto_publish": getattr(cls, "auto_publish", False),
                "immutable": getattr(cls, "immutable", False),
            }
            for name, cls in sorted(gateways.items())
        ]
        return JSONResponse({"gateways": items, "total": len(items)})

    # ------------------------------------------------------------------
    # GET /api/gateways/{name}
    # ------------------------------------------------------------------

    async def get_gateway(request: Request) -> JSONResponse:
        """Return metadata for a single installed gateway, including recent jobs."""
        name = request.path_params["name"]
        gateways = discover_gateways()
        cls = gateways.get(name)
        if cls is None:
            return JSONResponse(
                {"error": f"Gateway {name!r} not found.", "available": sorted(gateways)},
                status_code=404,
            )

        client = _build_cms_client(cms)
        try:
            recent = await _recent_jobs(client, name)
        finally:
            await client.close()

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
        logger.info(
            "starlette_cms_gateways.admin.sync_triggered",
            gateway=name,
            run_id=run_id,
        )

        async def _run_sync() -> None:
            writer = _build_cms_client(cms)
            try:
                # Write the start record
                start_doc = await _create_job_doc(writer, run_id, name)
                start_doc_id = start_doc["id"]

                # Run the actual gateway sync
                gateway_client = _build_cms_client(cms)
                try:
                    gateway = cls(cms_client=gateway_client)
                    result = await gateway.sync()
                finally:
                    await gateway_client.close()

                await _finish_job_doc(
                    writer,
                    start_doc_id,
                    status="done",
                    finished_at=datetime.now(UTC).isoformat(),
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
                err_msg = str(exc)
                logger.error(
                    "starlette_cms_gateways.admin.sync_error",
                    gateway=name,
                    run_id=run_id,
                    exc_info=exc,
                )
                # Best-effort: try to write error state if start doc was created
                try:
                    # Re-read start doc to get its id
                    data = await writer.list_documents(
                        import_ref=f"gateway_sync_job:{run_id}", limit=1
                    )
                    docs = data.get("documents", [])
                    if docs:
                        await _finish_job_doc(
                            writer,
                            docs[0]["id"],
                            status="error",
                            finished_at=datetime.now(UTC).isoformat(),
                            error=err_msg,
                        )
                except Exception:  # noqa: BLE001
                    pass
            finally:
                await writer.close()

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
        client = _build_cms_client(cms)
        try:
            job = await _read_job(client, run_id)
        finally:
            await client.close()

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
