"""
CMS — the main entry point for starlette-cms.

Usage::

    from starlette_cms import CMS

    cms = CMS(database_url="sqlite:///content.db", auth="apikey", api_key="secret")

    # Register blocks, documents, extension routes — then access cms.app
    app = Starlette(routes=[Mount("/cms", app=cms.app)], lifespan=cms.lifespan)
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from starlette_cms.media import MediaBackend
from starlette_cms.model_builder import build_document_model
from starlette_cms.registry import BlockRegistry


class CMS:
    """
    Mountable Starlette CMS sub-application.

    :param database_url: SQLite or Postgres connection string.
    :param auth: "none", "apikey", or an async callable (request) -> bool.
    :param api_key: Required when auth="apikey".
    :param read_auth: If True, protect GET endpoints with auth too.
    :param mount_path: The path this CMS is mounted at (used for self-links).
    :param discover_blocks: If True, auto-discover blocks via entry points.
    :param media_backend: Optional :class:`~starlette_cms.media.MediaBackend`
        implementation.  When set, ``ImageField`` values are validated against
        the backend on document create/patch.
    """

    def __init__(
        self,
        *,
        database_url: str,
        auth: str | Callable = "none",
        api_key: str | None = None,
        read_auth: bool = False,
        mount_path: str = "/cms",
        discover_blocks: bool = False,
        media_backend: MediaBackend | None = None,
    ) -> None:
        self.database_url = database_url
        self.auth = auth
        self.api_key = api_key
        self.read_auth = read_auth
        self.mount_path = mount_path
        self.media_backend = media_backend

        self.registry = BlockRegistry()
        self._document_types: dict[str, type] = {}
        self._extension_routes: list[dict[str, Any]] = []
        self._migrations: list[dict[str, Any]] = []
        self._app: Starlette | None = None  # built lazily on first access
        self._db: Any = None  # CMSDatabase instance, set in lifespan

        if discover_blocks:
            self._discover_blocks()

    # ------------------------------------------------------------------
    # Block registration
    # ------------------------------------------------------------------

    def block(
        self,
        name: str,
        *,
        singleton: bool = False,
        append_only: bool = False,
        override: bool = False,
    ):
        """
        First-party block decorator — defines and immediately registers a block::

            @cms.block("hero")
            class HeroBlock:
                title: str = TextField(required=True)

        Pass ``singleton=True`` for singleton (governed config) blocks::

            @cms.block("storage_rates", singleton=True)
            class StorageRates:
                rate: float = NumberField(default=0.005)

        Pass ``append_only=True`` for machine-written audit records that are
        immutable once created (ADR 014).  Documents of this type are
        auto-published on creation; PATCH and DELETE return 405::

            @cms.block("job_audit", append_only=True)
            class JobAudit:
                job_id: str = TextField(required=True, immutable=True)

        The class is converted to a Pydantic model before registration. The
        *decorated name* is rebound to the generated model so later references
        (e.g. inside ListField) pick up the Pydantic class.
        """

        def decorator(cls):
            cls.__block_type__ = name
            cls.__singleton__ = singleton
            cls.__append_only__ = append_only
            self.registry.register_block(
                cls, override=override, singleton=singleton, append_only=append_only
            )
            # Return the Pydantic model so the decorated name is the model
            return self.registry.get(name)

        return decorator

    @property
    def documents(self) -> CMSDocuments:
        """Python accessor for document operations (e.g. ``get_singleton``)."""
        return CMSDocuments(self)

    def register_block(self, block_cls: type, *, override: bool = False) -> None:
        """Register a pre-decorated block class. The class must have ``__block_type__`` set."""
        self.registry.register_block(block_cls, override=override)

    def register_blocks(self, block_classes: list[type], *, override: bool = False) -> None:
        """Register multiple pre-decorated block classes at once."""
        self.registry.register_blocks(block_classes, override=override)

    # ------------------------------------------------------------------
    # Document registration
    # ------------------------------------------------------------------

    def document(self, name: str):
        """Register a document type::

            @cms.document("page")
            class PageDocument:
                title: str = TextField(required=True)
                slug: str = TextField(required=True)
                body: list = ListField(blocks=[HeroBlock])

        The class is converted to a Pydantic model before storage.
        """

        # Fields that exist as top-level columns on CMSDocument — defining them
        # in the body schema is always a mistake and will cause them to appear
        # twice (once from the CMS row, once from the body JSON).
        _RESERVED_FIELDS = {"id", "slug", "doc_type", "published", "created_at", "updated_at", "meta"}

        def decorator(cls):
            # Warn loudly if any body field shadows a CMS system field
            body_fields = {
                k for k, v in vars(cls).items()
                if not k.startswith("_") and not callable(v)
            }
            shadowed = body_fields & _RESERVED_FIELDS
            if shadowed:
                import warnings
                warnings.warn(
                    f"@cms.document({name!r}): body field(s) {sorted(shadowed)} shadow CMS "
                    f"system fields. These fields are already tracked at the top level of every "
                    f"document — remove them from the body schema to avoid duplicates in the editor "
                    f"and ambiguity in the API response.",
                    stacklevel=3,
                )

            cls.__document_type__ = name
            model = build_document_model(name, cls)
            self._document_types[name] = model
            # Also register in the block registry so /api/schema includes document types
            model.__block_type__ = name
            self.registry.register_block(model, override=True)
            return model

        return decorator

    # ------------------------------------------------------------------
    # Extension routes (used by starlette-editor and other plugins)
    # ------------------------------------------------------------------

    def register_extension_route(
        self,
        *,
        path: str,
        endpoint: Callable,
        methods: list[str],
        name: str,
    ) -> None:
        """
        Register an additional route on the CMS before cms.app is built.
        Must be called before the first access of cms.app.
        """
        if self._app is not None:
            raise RuntimeError(
                "register_extension_route() must be called before cms.app is first accessed."
            )
        self._extension_routes.append(
            {
                "path": path,
                "endpoint": endpoint,
                "methods": methods,
                "name": name,
            }
        )

    # ------------------------------------------------------------------
    # Migrations
    # ------------------------------------------------------------------

    def migration(self, *, from_version: str, to_version: str):
        """Register an application migration function."""

        def decorator(fn):
            self._migrations.append(
                {
                    "from_version": from_version,
                    "to_version": to_version,
                    "fn": fn,
                }
            )
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Lazy app property
    # ------------------------------------------------------------------

    @property
    def app(self) -> Starlette:
        """Build and return the Starlette sub-application. Built once on first access."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        # Import here to avoid circular imports at module level
        from starlette_cms.api.documents import make_document_routes
        from starlette_cms.api.schema import make_schema_routes
        from starlette_cms.api.webhooks import make_webhook_routes

        routes: list[Route] = [
            *make_document_routes(self),
            *make_schema_routes(self),
            *make_webhook_routes(self),
            *[
                Route(r["path"], endpoint=r["endpoint"], methods=r["methods"], name=r["name"])
                for r in self._extension_routes
            ],
        ]
        return Starlette(routes=routes)

    # ------------------------------------------------------------------
    # Lifespan
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def lifespan_context(self, app) -> AsyncGenerator[None, None]:
        """Composable lifespan context manager."""
        from starlette_cms import __version__
        from starlette_cms.db import CMSDatabase

        self._db = CMSDatabase(
            database_url=self.database_url,
            schema_version=__version__,
        )
        await self._db.init()
        try:
            yield
        finally:
            await self._db.close()

    @asynccontextmanager
    async def lifespan(self, app) -> AsyncGenerator[None, None]:
        """Standalone lifespan — use when CMS is the only plugin."""
        async with self.lifespan_context(app):
            yield

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _discover_blocks(self) -> None:
        """Auto-discover blocks via importlib entry points."""
        from importlib.metadata import entry_points

        eps = entry_points(group="starlette_cms.blocks")
        for ep in eps:
            cls = ep.load()
            self.registry.register_block(cls)


class CMSDocuments:
    """
    Python accessor for document operations attached to a CMS instance.

    Available via ``cms.documents``::

        rates = await cms.documents.get_singleton("storage_rates")
        rate  = rates["body"]["bank_vault"]
    """

    def __init__(self, cms: CMS) -> None:
        self._cms = cms

    async def get_singleton(self, block_type: str) -> dict:
        """
        Return the currently active singleton document for *block_type*.

        Raises :exc:`~starlette_cms.exceptions.DocumentNotFound` if no
        published singleton exists yet.
        """
        from starlette_cms.api.documents import _row_to_dict
        from starlette_cms.exceptions import DocumentNotFound
        from starlette_cms.tables import CMSDocument

        rows = await (
            CMSDocument.select()
            .where(
                CMSDocument.doc_type == block_type,
                CMSDocument.singleton_status == "active",
            )
            .limit(1)
            .run()
        )
        if not rows:
            raise DocumentNotFound(f"No published singleton for {block_type!r}")
        return _row_to_dict(rows[0])

    async def list(
        self,
        block_type: str,
        *,
        filters: dict[str, Any] | None = None,
        published: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        List documents of a given block type with optional body filters.

        Example::

            scenarios = await cms.documents.list(
                "test_scenario",
                filters={"active": True, "category": "jewelry"},
                published=True,
            )
        """
        from starlette_cms.api.documents import _matches_filters, _row_to_dict
        from starlette_cms.tables import CMSDocument

        query = CMSDocument.select().where(CMSDocument.doc_type == block_type)

        if published is not None:
            query = query.where(CMSDocument.published == published)

        query = query.order_by(CMSDocument.created_at, ascending=False)

        all_rows = await query.run()
        all_docs = [_row_to_dict(r) for r in all_rows]

        if filters:
            all_docs = [d for d in all_docs if _matches_filters(d, filters)]

        return all_docs[offset : offset + limit]
