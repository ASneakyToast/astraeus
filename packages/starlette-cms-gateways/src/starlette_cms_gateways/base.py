"""
BaseGateway ABC and associated data types.

Gateway authors subclass :class:`BaseGateway`, set three class-level attributes,
and implement a single :meth:`~BaseGateway.fetch` async generator.  The
framework handles deduplication, upsert, and result reporting.

Observability (last-sync timestamps, per-run metrics) is the gateway's own
responsibility — use OpenTelemetry spans/metrics or your own state store.

Usage::

    from starlette_cms_gateways import BaseGateway, GatewayItem
    from collections.abc import AsyncIterator

    class SpotifyLikedSongsGateway(BaseGateway):
        service_name = "spotify_liked_songs"
        block_type   = "spotify_liked_song"
        auto_publish = True

        async def fetch(self) -> AsyncIterator[GatewayItem]:
            async for track in spotify_client.iter_liked_songs():
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
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Literal

import structlog
from opentelemetry import trace
from opentelemetry.trace import StatusCode

if TYPE_CHECKING:
    from starlette_cms_gateways.client import CMSClient
    from starlette_cms_gateways.jobstore import JobStore

tracer = trace.get_tracer(__name__)
logger = structlog.get_logger(__name__)


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

    def owned_body(self, owned_fields: Iterable[str] | None = None) -> dict[str, Any]:
        """
        Return the part of the body the gateway owns.

        ``None`` means every field is owned (the pre-ownership behaviour).
        Fields named in *owned_fields* but absent from the body are left out.
        """
        if owned_fields is None:
            return self.body
        return {k: self.body[k] for k in owned_fields if k in self.body}

    def content_hash(self, owned_fields: Iterable[str] | None = None) -> str:
        """
        Return a short SHA-256 hex digest of the gateway-owned part of the body.

        Used to detect whether an already-synced document needs updating.
        Only owned fields are hashed, so a field the gateway merely seeds on
        creation (a title a human may edit) never triggers an update.
        """
        serialised = json.dumps(
            self.owned_body(owned_fields), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]


SyncMode = Literal["since_last_sync", "all_time", "custom"]
SYNC_MODES: tuple[str, ...] = ("since_last_sync", "all_time", "custom")


@dataclass(frozen=True)
class SyncRange:
    """
    What a sync run was asked to cover.

    * ``since_last_sync`` — only what changed since the last clean run (needs a
      cursor; with none stored the run widens to ``all_time``).
    * ``all_time`` — everything. Use for a first run or to repair.
    * ``custom`` — a backfill of the *content* dates ``start``..``end``
      (inclusive, either may be open). What "content date" means is the
      gateway's call: an observed date, a liked-at month. A custom run never
      moves the cursor.
    """

    mode: SyncMode = "since_last_sync"
    start: date | None = None
    end: date | None = None

    def __post_init__(self) -> None:
        if self.mode not in SYNC_MODES:
            raise ValueError(f"Unknown sync range {self.mode!r}; expected one of {SYNC_MODES}")
        if self.mode == "custom":
            if self.start is None and self.end is None:
                raise ValueError("A custom range needs a start date, an end date, or both")
            if self.start and self.end and self.start > self.end:
                raise ValueError(f"Custom range start {self.start} is after end {self.end}")
        elif self.start is not None or self.end is not None:
            raise ValueError(f"Dates are only valid with mode='custom', not {self.mode!r}")

    @classmethod
    def parse(
        cls,
        mode: str | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
        *,
        default: SyncMode = "since_last_sync",
    ) -> SyncRange:
        """Build a range from loose input (CLI flags, JSON, MCP arguments)."""
        s = date.fromisoformat(start) if isinstance(start, str) and start else start or None
        e = date.fromisoformat(end) if isinstance(end, str) and end else end or None
        chosen = mode or ("custom" if (s or e) else default)
        return cls(chosen, s, e)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SyncWindow:
    """
    The range a gateway resolves for itself with :meth:`BaseGateway.resolve_window`.

    :param mode: What the run will actually do. A ``since_last_sync`` request
        with no stored cursor resolves to ``all_time`` (``fell_back`` is True).
    :param changed_since: Only set for an incremental run: fetch what changed
        at the source after this moment (the cursor, pulled back by the
        gateway's overlap).
    :param start: / ``end`` Content-date bounds, only set for ``custom``.
    """

    mode: SyncMode = "all_time"
    changed_since: datetime | None = None
    start: date | None = None
    end: date | None = None
    fell_back: bool = False

    @classmethod
    def resolve(
        cls, requested: SyncRange, cursor: datetime | None, overlap: timedelta
    ) -> SyncWindow:
        if requested.mode == "custom":
            return cls("custom", None, requested.start, requested.end)
        if requested.mode == "since_last_sync":
            if cursor is None:
                return cls("all_time", fell_back=True)
            return cls("since_last_sync", changed_since=cursor - overlap)
        return cls("all_time")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "changed_since": self.changed_since.isoformat() if self.changed_since else None,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "fell_back": self.fell_back,
        }


@dataclass
class SyncResult:
    """
    Summary of a single gateway sync run.

    :param created: Number of new documents created.
    :param updated: Number of existing documents updated.
    :param skipped: Number of documents skipped (identical content).
    :param deferred: ``import_ref`` of documents the run left alone because a
        human holds a pending draft on them (or unpublished them). They are
        retried on the next run; until then the cursor does not advance.
    :param window: The :class:`SyncWindow` the run actually covered.
    :param errors: List of ``(import_ref, error_message)`` pairs.
    :param changeset_id: The changeset the run's writes were grouped into, or
        ``None`` when the run wrote nothing (all skipped).
    :param started_at: UTC timestamp when the sync started.
    :param finished_at: UTC timestamp when the sync finished.
    """

    created: int = 0
    updated: int = 0
    skipped: int = 0
    deferred: list[str] = field(default_factory=list)
    window: SyncWindow | None = None
    errors: list[tuple[str, str]] = field(default_factory=list)
    changeset_id: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def total(self) -> int:
        """Total items processed (created + updated + skipped + deferred)."""
        return self.created + self.updated + self.skipped + len(self.deferred)

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
            "deferred": self.deferred,
            "window": self.window.to_dict() if self.window else None,
            "errors": self.errors,
            "changeset_id": self.changeset_id,
            "total": self.total,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class BaseGateway(ABC):
    """
    Abstract base class for CMS gateway implementations.

    Subclass this and implement :meth:`fetch`.  Set three class attributes::

        class MyGateway(BaseGateway):
            service_name = "my_service"     # unique key
            block_type   = "my_block"       # CMS block type for synced docs
            auto_publish = False            # default: create as drafts

    The framework-provided :meth:`sync` method handles the full fetch →
    upsert loop.  Call it via the CLI (``gateways sync``) or directly in
    your own code::

        gateway = MyGateway(cms_client=CMSClient(...))
        result = await gateway.sync()

    :param cms_client: A :class:`~starlette_cms_gateways.client.CMSClient`
        instance connected to your CMS.
    """

    # -----------------------------------------------------------------------
    # Class-level attributes — set by each subclass
    # -----------------------------------------------------------------------

    service_name: ClassVar[str]
    """Unique service identifier."""

    block_type: ClassVar[str]
    """CMS block type name for synced documents."""

    auto_publish: ClassVar[bool] = False
    """If False (default), documents are created as drafts and must be explicitly
    published.  Set True to publish immediately on creation or update.
    """

    owned_fields: ClassVar[tuple[str, ...] | None] = None
    """The body fields this gateway owns — the machine-sourced ones.

    Only these are hashed and only these are written when an existing document
    is updated. Everything else in :attr:`GatewayItem.body` is written once, at
    creation, and then belongs to whoever edits it (a title, commentary, tags).
    ``None`` (default) keeps the old behaviour: every field is owned.
    """

    default_range: ClassVar[SyncMode] = "since_last_sync"
    """What :meth:`sync` covers when the caller names no range."""

    cursor_overlap: ClassVar[timedelta] = timedelta(days=1)
    """How far an incremental run reaches back before the stored cursor, so a
    change that landed near the previous run's start is not missed."""

    immutable: ClassVar[bool] = False
    """If True, register the gateway's block type with ``append_only=True`` in the CMS.
    Use for audit-style gateways where records should never be modified after creation.
    Default False — synced items are mutable so annotations can be added after sync.
    """

    # -----------------------------------------------------------------------
    # Constructor
    # -----------------------------------------------------------------------

    def __init__(
        self,
        *,
        cms_client: CMSClient,
        job_store: JobStore | None = None,
        job_store_key: str | None = None,
    ) -> None:
        self._client = cms_client
        self._job_store = job_store
        # Key used for job history lookups — defaults to service_name.
        self._job_store_key: str = job_store_key or self.service_name
        # What the current sync() was asked to cover. Set for every run; a gateway
        # that wants incremental behaviour reads it in fetch() (see resolve_window).
        self.range: SyncRange = SyncRange(self.default_range)
        # Set only if fetch() called resolve_window(); gates cursor advancement.
        self._window: SyncWindow | None = None

    # -----------------------------------------------------------------------
    # Abstract method — gateway authors implement this
    # -----------------------------------------------------------------------

    @abstractmethod
    def fetch(self) -> AsyncIterator[GatewayItem]:
        """
        Yield items from the external service.

        This method is an async generator — use ``yield`` to emit items one at
        a time.  The framework calls :meth:`sync` which iterates this generator
        and upserts each item into the CMS.

        The framework does not hand you a ``since``: cursors come in too many
        shapes (ADR 015). Read ``self.range`` for what was asked, and call
        :meth:`resolve_window` if a datetime cursor suits your source — it
        returns the window to fetch and arms the framework to advance the cursor
        after a clean run. A gateway that never calls it is unaffected.
        """
        ...

    # -----------------------------------------------------------------------
    # Framework-provided sync loop
    # -----------------------------------------------------------------------

    async def resolve_window(self) -> SyncWindow:
        """
        Turn ``self.range`` into the window to fetch — opt-in helper for ``fetch()``.

        ``since_last_sync`` becomes an incremental window starting
        :attr:`cursor_overlap` before the stored cursor, or an ``all_time`` window
        when there is no cursor yet (no job store wired, or a first run). Calling
        this also tells the framework to advance the cursor if the run ends
        clean, via :meth:`next_cursor`.
        """
        cursor = (
            await self._job_store.get_cursor(self._job_store_key)
            if self._job_store is not None
            else None
        )
        self._window = SyncWindow.resolve(self.range, cursor, self.cursor_overlap)
        if self._window.fell_back:
            logger.info(
                "starlette_cms_gateways.sync.no_cursor",
                gateway=self.service_name,
                detail="since_last_sync requested but no cursor stored; syncing all time",
            )
        return self._window

    def next_cursor(self, result: SyncResult) -> datetime:
        """
        The cursor to store after a clean run. Default: when the run started.

        Override to store something else. The start time, not the finish time:
        anything that changed at the source while the run was in flight is then
        picked up by the next one.
        """
        return result.started_at

    async def sync(self, range: SyncRange | None = None) -> SyncResult:  # noqa: A002
        """
        Run a sync cycle for this gateway.

        1. Record *range* (default :attr:`default_range`) as ``self.range``.
        2. Call :meth:`fetch` to get items from the external service.
        3. For each :class:`GatewayItem` yielded:

           a. Check for an existing document by ``import_ref``.
           b. If none → create.
           c. If the hash of the owned fields changed → update those fields only.
           d. If identical → skip, writing nothing.
           e. If a human holds a pending draft on it → defer, writing nothing.

        4. When the gateway auto-publishes, publish the run's changeset once.
        5. Advance the cursor — only for a gateway that called
           :meth:`resolve_window`, only if the run finished cleanly (no
           exception, no item errors, nothing deferred), and never for a
           ``custom`` backfill.

        :param range: Override the gateway's default range for this run.
        :returns: :class:`SyncResult` with create/update/skip counts.
        """
        result = SyncResult()
        self.range = range or SyncRange(self.default_range)
        self._window = None

        # Group every write in this run into one changeset, created lazily on the
        # first create/update so an all-skip run leaves no empty changeset behind.
        async def get_run_changeset() -> str:
            if result.changeset_id is None:
                title = f"{self.service_name} sync — {datetime.now(UTC).strftime('%b %-d')}"
                result.changeset_id = await self._client.create_changeset(title)
            return result.changeset_id

        publish_run_changeset = False

        with tracer.start_as_current_span("gateways.sync") as span:
            span.set_attribute("gateway_name", self.service_name)
            span.set_attribute("sync_range", self.range.mode)
            try:
                try:
                    async for item in self.fetch():
                        try:
                            publish = (
                                self.auto_publish if item.published is None else item.published
                            )
                            # On an auto-publishing gateway the run changeset is published
                            # once at the end, so an item that opts out (published=False)
                            # must stay out of it. Everywhere else the run changeset is
                            # the review batch, as before.
                            batched = publish and self.auto_publish
                            in_run_changeset = publish or not self.auto_publish
                            action = await self._client.upsert(
                                item=item,
                                block_type=self.block_type,
                                auto_publish=publish,
                                changeset_provider=get_run_changeset if in_run_changeset else None,
                                owned_fields=self.owned_fields,
                                publish_with_changeset=batched,
                            )
                            if action == "created":
                                result.created += 1
                                publish_run_changeset |= batched
                            elif action == "updated":
                                result.updated += 1
                                publish_run_changeset |= batched
                            elif action == "deferred":
                                result.deferred.append(item.import_ref)
                            else:
                                result.skipped += 1
                        except Exception as exc:  # noqa: BLE001
                            result.errors.append((item.import_ref, str(exc)))
                finally:
                    # Publish what was written even if a later fetch page failed,
                    # so a crash never strands half a run as open drafts.
                    if publish_run_changeset and result.changeset_id is not None:
                        await self._client.publish_changeset(result.changeset_id)

                result.finish()
                result.window = self._window
                span.set_attribute("item_count", result.total)

                clean = not result.errors and not result.deferred
                if (
                    clean
                    and self._window is not None
                    and self._window.mode != "custom"
                    and self._job_store is not None
                ):
                    cursor = self.next_cursor(result)
                    await self._job_store.set_cursor(self._job_store_key, cursor)
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                raise

        return result
