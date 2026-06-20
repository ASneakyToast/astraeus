"""
GatewaySyncState — singleton block type for persisting gateway sync state.

The sync state is stored as a CMS singleton document, queryable via the
CMS API and MCP tools.  One singleton holds the state for ALL gateways
registered in the system — each service gets its own entry under the
``services`` key of the body.

Structure::

    {
        "services": {
            "spotify_liked_songs": {
                "last_synced": "2026-06-19T12:00:00+00:00",
                "last_result": {
                    "created": 5,
                    "updated": 2,
                    "skipped": 10,
                    "errors":  [],
                    "total":   17,
                    ...
                }
            },
            "inaturalist_outings": { ... }
        }
    }

The ``GatewaySyncStateBlock`` class is provided as a plain Python class, not
as a Pydantic model, because the ``services`` sub-structure is open-ended.
Use :func:`register` to wire it into a CMS instance as a ``singleton=True``
block via ``JSONField``.

Usage::

    from starlette_cms_gateways.blocks import register as register_gateway_blocks
    register_gateway_blocks(cms)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette_cms_gateways.base import SyncResult


class GatewaySyncStateBlock:
    """
    Helper for constructing and reading ``gateway_sync_state`` singleton bodies.

    Not a Pydantic model — the body is an open-ended dict stored in a
    ``JSONField``.  See module docstring for the body structure.
    """

    BLOCK_TYPE = "gateway_sync_state"

    @staticmethod
    def make_body(
        *,
        service_name: str,
        last_synced: datetime,
        result: SyncResult,
    ) -> dict[str, Any]:
        """
        Build the per-service body dict to pass to
        :meth:`~starlette_cms_gateways.client.CMSClient.save_sync_state`.

        The returned dict uses the *full* singleton body shape so that
        ``save_sync_state`` can merge it with existing service entries.

        :param service_name: The ``service_name`` attribute of the gateway.
        :param last_synced: The UTC timestamp when the sync finished.
        :param result: The :class:`~starlette_cms_gateways.base.SyncResult` from
            the sync run.
        :returns: Dict with a single ``"services"`` key containing the new
            entry for this service.
        """
        if last_synced.tzinfo is None:
            last_synced = last_synced.replace(tzinfo=UTC)

        return {
            "services": {
                service_name: {
                    "last_synced": last_synced.isoformat(),
                    "last_result": result.to_dict(),
                }
            }
        }

    @staticmethod
    def get_last_synced(body: dict[str, Any], service_name: str) -> datetime | None:
        """
        Extract the last-synced timestamp for ``service_name`` from a
        ``gateway_sync_state`` body dict.

        :returns: A timezone-aware :class:`datetime`, or ``None`` if absent.
        """
        services = body.get("services") or {}
        entry = services.get(service_name) or {}
        ts_str = entry.get("last_synced")
        if not ts_str:
            return None
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            return None


def register(cms: Any) -> None:
    """
    Register the ``gateway_sync_state`` singleton block type on a CMS instance.

    Call this during application startup, before ``cms.app`` is accessed::

        from starlette_cms import CMS
        from starlette_cms_gateways.blocks import register as register_gateway_blocks

        cms = CMS(database_url="sqlite:///content.db")
        register_gateway_blocks(cms)

    The block is registered as a singleton with a single :class:`JSONField`
    that holds the full sync-state structure.

    :param cms: A :class:`~starlette_cms.app.CMS` instance.
    """
    from starlette_cms.fields import JSONField
    from starlette_cms.registry import block

    @block(GatewaySyncStateBlock.BLOCK_TYPE, singleton=True)
    class _GatewaySyncState:
        services: dict = JSONField()  # type: ignore[assignment]

    cms.register_block(_GatewaySyncState)
