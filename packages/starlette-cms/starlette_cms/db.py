"""
Database initialisation and lifecycle for starlette-cms.

``CMSDatabase`` parses ``database_url``, assigns the engine to the Piccolo
table classes, creates tables on first startup, and closes the connection on
shutdown.

Usage::

    db = CMSDatabase(database_url="sqlite:///content.db")
    await db.init()
    # ... serve requests ...
    await db.close()

Supported URL schemes:

- ``sqlite:///path/to/file.db`` — aiosqlite (bundled with piccolo)
- ``sqlite://:memory:`` — in-memory SQLite (shared-cache URI form; use only
  in tests, not in production)
- ``postgres://user:pass@host/db`` or ``postgresql://...`` — asyncpg
"""

from __future__ import annotations

import warnings
from urllib.parse import urlparse

import structlog

from starlette_cms.tables import CMSDocument, CMSMeta, CMSWebhook

logger = structlog.get_logger(__name__)


class CMSDatabase:
    """
    Manages the Piccolo engine lifecycle for starlette-cms.

    :param database_url: SQLite or Postgres connection string.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._engine = None

    async def init(self) -> None:
        """
        Parse ``database_url``, assign engine to table classes, create tables,
        and enable WAL mode for SQLite.
        """
        engine = self._build_engine(self.database_url)
        self._engine = engine

        # Assign to all table classes
        CMSDocument._meta.db = engine
        CMSMeta._meta.db = engine
        CMSWebhook._meta.db = engine

        # SQLite: start connection pool (no-op for SQLite — piccolo emits a
        # warning which we suppress; the call is safe to make)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                await engine.start_connection_pool()
        except Exception:
            pass  # Not all engines support pooling

        # Create tables (zero-config dev experience — safe on existing DBs)
        await CMSDocument.create_table(if_not_exists=True)
        await CMSMeta.create_table(if_not_exists=True)
        await CMSWebhook.create_table(if_not_exists=True)
        logger.debug("starlette_cms.db.tables_ready", database_url=self.database_url)

        # Enable WAL mode for SQLite (improves concurrent read performance)
        if engine.engine_type == "sqlite":
            try:
                await engine.run_ddl("PRAGMA journal_mode=WAL")
            except Exception:
                pass  # Ignore failures on read-only or in-memory databases

    async def close(self) -> None:
        """Close the engine connection pool."""
        if self._engine is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    await self._engine.close_connection_pool()
            except Exception:
                pass

    @staticmethod
    def _build_engine(database_url: str):
        """
        Parse ``database_url`` and return the appropriate Piccolo engine.

        Supported schemes: ``sqlite``, ``postgres``, ``postgresql``.
        """
        parsed = urlparse(database_url)
        scheme = parsed.scheme.lower()

        if scheme == "sqlite":
            from piccolo.engine.sqlite import SQLiteEngine

            # URL forms:
            #   sqlite:///path/to/file.db  → parsed.path = "/path/to/file.db"
            #   sqlite:////abs/path.db     → parsed.path = "//abs/path.db"  (double-slash form)
            #   sqlite:///:memory:         → parsed.path = "/:memory:"
            path = parsed.path
            # Normalise :memory: (strip the leading slash added by urlparse)
            stripped = path.lstrip("/")
            if stripped == ":memory:":
                # Use a shared-cache URI so all async connections see the same data.
                # pytest-asyncio creates a new event-loop per test, so tests should
                # use a temp file instead. This mode is provided for compatibility.
                return SQLiteEngine(path="file::memory:?cache=shared", uri=True)
            # Double-slash means the caller used four slashes (sqlite:////abs/path.db)
            # which is an absolute path; strip one leading slash so we end up with /abs/path.db.
            if path.startswith("//"):
                path = path[1:]
            # path now starts with "/" for absolute paths or "./" for relative — both are valid
            # for SQLiteEngine.
            return SQLiteEngine(path=path)

        if scheme in ("postgres", "postgresql"):
            try:
                from piccolo.engine.postgres import PostgresEngine
            except ImportError as exc:
                raise RuntimeError(
                    "asyncpg is required for Postgres support. "
                    "Install it with: pip install starlette-cms[postgres]"
                ) from exc

            # piccolo PostgresEngine accepts a config dict
            config: dict = {
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "user": parsed.username or "postgres",
                "password": parsed.password or "",
                "database": parsed.path.lstrip("/"),
            }
            return PostgresEngine(config=config)

        raise ValueError(
            f"Unsupported database_url scheme: {scheme!r}. Use 'sqlite:///...' or 'postgres://...'."
        )
