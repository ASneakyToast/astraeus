"""
Where a gateway keeps what it must remember between runs.

Three things outlive a run: the **cursor** (the start time of the last run that
did not raise), the **retry list** (documents a run could not finish and the
next one should try again) and the **job history** (for "last synced").

They live in the CMS's own database. A worker that is not the CMS process (the
``gateways`` CLI, an MCP sidecar in another pod) cannot open that file, so it
reads and writes them through the CMS gateway API instead. Both ways satisfy
:class:`SyncState`: :class:`~starlette_cms_gateways.jobstore.JobStore` is the
local SQLite implementation, :class:`RemoteSyncState` the HTTP one. Either way
there is one cursor per gateway, not one per process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from starlette_cms_gateways.client import CMSClient

RetryReason = Literal["deferred", "error"]


@dataclass(frozen=True)
class RetryEntry:
    """A document the last run could not finish.

    :param import_ref: The document's ``import_ref``.
    :param reason: ``deferred`` (a person's draft or unpublish is in the way) or
        ``error`` (the write failed).
    :param detail: The error message, for ``error``.
    :param since: When it first went on the list; kept while it stays there.
    """

    import_ref: str
    reason: RetryReason
    detail: str = ""
    since: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "import_ref": self.import_ref,
            "reason": self.reason,
            "detail": self.detail,
            "since": self.since,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryEntry:
        reason = data.get("reason", "deferred")
        if reason not in ("deferred", "error"):
            raise ValueError(f"Unknown retry reason {reason!r}")
        return cls(
            import_ref=str(data["import_ref"]),
            reason=reason,
            detail=str(data.get("detail", "")),
            since=str(data.get("since") or datetime.now(UTC).isoformat()),
        )


@runtime_checkable
class SyncState(Protocol):
    """What :class:`~starlette_cms_gateways.base.BaseGateway` needs to remember."""

    async def get_cursor(self, key: str) -> datetime | None: ...

    async def set_cursor(self, key: str, cursor: datetime) -> None: ...

    async def get_retry(self, key: str) -> list[RetryEntry]: ...

    async def set_retry(self, key: str, entries: list[RetryEntry]) -> None: ...

    async def create(self, run_id: str, gateway_name: str) -> None: ...

    async def finish(
        self,
        run_id: str,
        *,
        status: str,
        created: int = 0,
        updated: int = 0,
        skipped: int = 0,
        errors: list | None = None,
        error: str = "",
        deferred: list | None = None,
        range: dict | None = None,  # noqa: A002
    ) -> None: ...


class RemoteSyncState:
    """
    :class:`SyncState` over the CMS gateway API.

    ``GET/PUT /api/gateways/{name}/cursor``, ``GET/PUT .../retry`` and
    ``POST /api/gateways/{name}/runs`` + ``PATCH .../runs/{run_id}``. Auth is
    whatever the :class:`CMSClient` carries.
    """

    def __init__(self, client: CMSClient) -> None:
        self._client = client
        # run_id → gateway name, so finish() can address the run's URL.
        self._runs: dict[str, str] = {}

    async def get_cursor(self, key: str) -> datetime | None:
        data = await self._client.gateway_request("GET", f"{key}/cursor")
        raw = data.get("cursor")
        return datetime.fromisoformat(raw) if raw else None

    async def set_cursor(self, key: str, cursor: datetime) -> None:
        await self._client.gateway_request("PUT", f"{key}/cursor", {"cursor": cursor.isoformat()})

    async def get_retry(self, key: str) -> list[RetryEntry]:
        data = await self._client.gateway_request("GET", f"{key}/retry")
        return [RetryEntry.from_dict(e) for e in data.get("entries", [])]

    async def set_retry(self, key: str, entries: list[RetryEntry]) -> None:
        await self._client.gateway_request(
            "PUT", f"{key}/retry", {"entries": [e.to_dict() for e in entries]}
        )

    async def create(self, run_id: str, gateway_name: str) -> None:
        await self._client.gateway_request("POST", f"{gateway_name}/runs", {"run_id": run_id})
        self._runs[run_id] = gateway_name

    async def finish(
        self,
        run_id: str,
        *,
        status: str,
        created: int = 0,
        updated: int = 0,
        skipped: int = 0,
        errors: list | None = None,
        error: str = "",
        deferred: list | None = None,
        range: dict | None = None,  # noqa: A002
    ) -> None:
        name = self._runs.pop(run_id)
        await self._client.gateway_request(
            "PATCH",
            f"{name}/runs/{run_id}",
            {
                "status": status,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "errors": errors or [],
                "error": error,
                "deferred": deferred or [],
                "range": range,
            },
        )
