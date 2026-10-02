"""
Run a gateway and keep its job history true.

Every way of running a sync (the admin API, the ``gateways`` CLI, an MCP tool)
goes through :func:`run_recorded`, so "last synced" and the job list reflect
runs from all of them, not only the ones started from the admin page.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from starlette_cms_gateways.base import BaseGateway, SyncRange, SyncResult
    from starlette_cms_gateways.state import SyncState

logger = structlog.get_logger(__name__)


async def run_recorded(
    gateway: BaseGateway,
    state: SyncState,
    name: str,
    sync_range: SyncRange | None = None,
    *,
    run_id: str | None = None,
) -> SyncResult:
    """
    Run ``gateway.sync(sync_range)`` and record the run in *state*.

    :param name: The gateway's entry-point name (the key its state is stored under).
    :param run_id: A run already created in *state* (the admin API creates it
        first so it can hand the id back). Created here when omitted.
    :raises: whatever ``sync`` raises, after recording the run as an error.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())
        await state.create(run_id, name)
    try:
        result = await gateway.sync(sync_range)
    except Exception as exc:
        await _finish(state, run_id, status="error", error=str(exc))
        raise
    await _finish(
        state,
        run_id,
        status="done",
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
        errors=[list(e) for e in result.errors],
        deferred=result.deferred,
        range=result.window.to_dict() if result.window else {"mode": gateway.range.mode},
    )
    return result


async def _finish(state: SyncState, run_id: str, **fields: Any) -> None:
    """Close the job record. A failure here must not lose a result that already exists."""
    try:
        await state.finish(run_id, **fields)
    except Exception as exc:  # noqa: BLE001
        logger.warning("starlette_cms_gateways.runner.finish_failed", run_id=run_id, error=str(exc))
