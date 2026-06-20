"""
BaseGateway ABC and associated data types.

Gateway authors subclass :class:`BaseGateway`, set three class-level attributes,
and implement a single :meth:`~BaseGateway.fetch` async generator.  The
framework handles deduplication, upsert, sync state, and result reporting.

Usage::

    from starlette_cms_gateways import BaseGateway, GatewayItem
    from collections.abc import AsyncIterator
    from datetime import datetime

    class SpotifyLikedSongsGateway(BaseGateway):
        service_name = "spotify_liked_songs"
        block_type   = "spotify_liked_song"
        auto_publish = True

        async def fetch(self, since: datetime | None) -> AsyncIterator[GatewayItem]:
            async for track in spotify_client.iter_liked_songs(after=since):
                yield GatewayItem(
                    import_ref=f"spotify:liked:{track['id']}",
                    slug=f"spotify-liked-{track['id']}",
                    body={
                        "track_name":  track["name"],
                        "artist_name": track["artists"][0]["name"],
                        "liked_at":    track["added_at"],
                    },
                )
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from starlette_cms_gateways.client import CMSClient


@dataclass
class GatewayItem:
    """
    A single item to be synced into the CMS.

    :param import_ref: Stable external ID — e.g. ``"spotify:liked:abc123"``.
        Must be unique within the ``(doc_type, import_ref)`` pair across the
        entire CMS.  See ADR 015.
    :param slug: URL-safe CMS slug.  Should be stable across re-syncs.
    :param body: Block field values.  Must validate against the registered
        block schema for the gateway's :attr:`~BaseGateway.block_type`.
    :param published: Override per-item publish behaviour.  Defaults to the
        gateway's :attr:`~BaseGateway.auto_publish` flag.
    :param title: Optional human-readable title (stored in CMS meta).
    """

    import_ref: str
    slug: str
    body: dict[str, Any]
    published: bool | None = None  # None → use gateway.auto_publish
    title: str = ""

    def content_hash(self) -> str:
        """
        Return a short SHA-256 hex digest of the body.

        Used to detect whether an already-synced document needs updating.
        """
        serialised = json.dumps(self.body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]


@dataclass
class SyncResult:
    """
    Summary of a single gateway sync run.

    :param created: Number of new documents created.
    :param updated: Number of existing documents updated.
    :param skipped: Number of documents skipped (identical content).
    :param errors: List of ``(import_ref, error_message)`` pairs.
    :param started_at: UTC timestamp when the sync started.
    :param finished_at: UTC timestamp when the sync finished.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def total(self) -> int:
        """Total items processed (created + updated + skipped)."""
        return self.created + self.updated + self.skipped

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def finish(self) -> None:
        """Mark the sync as finished (sets :attr:`finished_at`)."""
        self.finished_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
            "total": self.total,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class BaseGateway(ABC):
    """
    Abstract base class for CMS gateway implementations.

    Subclass this and implement :meth:`fetch`.  Set three class attributes::

        class MyGateway(BaseGateway):
            service_name = "my_service"     # unique key — used in sync state
            block_type   = "my_block"       # CMS block type for synced docs
            auto_publish = True             # publish immediately on sync

    The framework-provided :meth:`sync` method handles the full fetch →
    upsert → record-state loop.  Call it via the CLI (``gateways sync``) or
    directly in your own code::

        gateway = MyGateway(cms_client=CMSClient(...))
        result = await gateway.sync()

    :param cms_client: A :class:`~starlette_cms_gateways.client.CMSClient`
        instance connected to your CMS.
    """

    # -----------------------------------------------------------------------
    # Class-level attributes — set by each subclass
    # -----------------------------------------------------------------------

    service_name: ClassVar[str]
    """Unique service identifier.  Used as the sync state singleton key."""

    block_type: ClassVar[str]
    """CMS block type name for synced documents."""

    auto_publish: ClassVar[bool] = True
    """If True, documents are published immediately on creation or update."""

    # -----------------------------------------------------------------------
    # Constructor
    # -----------------------------------------------------------------------

    def __init__(self, *, cms_client: CMSClient) -> None:
        self._client = cms_client

    # -----------------------------------------------------------------------
    # Abstract method — gateway authors implement this
    # -----------------------------------------------------------------------

    @abstractmethod
    def fetch(self, since: datetime | None) -> AsyncIterator[GatewayItem]:
        """
        Yield items from the external service.

        :param since: The UTC datetime of the last successful sync, or ``None``
            on the first run (full refresh).  Use this to request only new or
            changed items from the upstream API.

        This method is an async generator — use ``yield`` to emit items one at
        a time.  The framework calls :meth:`sync` which iterates this generator
        and upserts each item into the CMS.
        """
        ...

    # -----------------------------------------------------------------------
    # Framework-provided sync loop
    # -----------------------------------------------------------------------

    async def sync(self, *, full_refresh: bool = False) -> SyncResult:
        """
        Run a full sync cycle for this gateway.

        1. Read last-sync state from the CMS (``GatewaySyncState`` singleton).
        2. Call :meth:`fetch` with ``since`` (or ``None`` on full refresh).
        3. For each :class:`GatewayItem` yielded:

           a. Check for an existing document by ``import_ref``.
           b. If none → create.
           c. If exists and body hash changed → update body.
           d. If exists and body identical → skip.

        4. Persist updated ``GatewaySyncState`` singleton.

        :param full_refresh: If True, ignore ``since`` and fetch everything.
        :returns: :class:`SyncResult` with create/update/skip counts.
        """
        from starlette_cms_gateways.blocks import GatewaySyncStateBlock

        result = SyncResult()

        # Read the last successful sync timestamp
        last_synced: datetime | None = None
        if not full_refresh:
            last_synced = await self._client.get_last_synced(self.service_name)

        # Iterate items from the external service
        async for item in self.fetch(None if full_refresh else last_synced):
            try:
                action = await self._client.upsert(
                    item=item,
                    block_type=self.block_type,
                    auto_publish=self.auto_publish
                    if item.published is None
                    else item.published,
                )
                if action == "created":
                    result.created += 1
                elif action == "updated":
                    result.updated += 1
                else:
                    result.skipped += 1
            except Exception as exc:  # noqa: BLE001
                result.errors.append((item.import_ref, str(exc)))

        result.finish()

        # Persist sync state back to the CMS
        state_body = GatewaySyncStateBlock.make_body(
            service_name=self.service_name,
            last_synced=result.finished_at or datetime.now(UTC),
            result=result,
        )
        await self._client.save_sync_state(
            service_name=self.service_name,
            body=state_body,
        )

        return result
