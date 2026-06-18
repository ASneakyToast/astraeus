"""
CLI entry point — ``cms migrate``, ``cms validate``

All commands that need a CMS instance accept ``--app MODULE:ATTRIBUTE``
(e.g. ``--app myapp:cms``), defaulting to the ``CMS_APP`` environment
variable.  The attribute must be a ``CMS`` instance — not a Starlette app.

Examples::

    # Show pending migrations
    cms migrate status --app myapp:cms

    # Preview without applying
    cms migrate --dry-run --app myapp:cms

    # Apply
    cms migrate --app myapp:cms

    # Re-validate all stored documents
    cms validate --app myapp:cms
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from starlette_cms.app import CMS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cms(app_spec: str) -> CMS:
    """
    Import and return a CMS instance from a ``module:attribute`` spec.

    :raises click.UsageError: if the spec is invalid or the attribute is not a CMS.
    """
    from starlette_cms.app import CMS as CMSClass

    if ":" not in app_spec:
        raise click.UsageError(
            f"Invalid --app value {app_spec!r}. Use MODULE:ATTRIBUTE format, e.g. 'myapp:cms'."
        )
    module_path, attr = app_spec.rsplit(":", 1)

    # Ensure the cwd is on sys.path so relative module names work
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise click.UsageError(f"Cannot import module {module_path!r}: {exc}") from exc

    obj = getattr(module, attr, None)
    if obj is None:
        raise click.UsageError(f"Module {module_path!r} has no attribute {attr!r}.")
    if not isinstance(obj, CMSClass):
        raise click.UsageError(
            f"{module_path}:{attr} is a {type(obj).__name__}, not a CMS instance."
        )
    return obj


def _app_option(f):
    """Shared --app / CMS_APP option decorator."""
    return click.option(
        "--app",
        "app_spec",
        default=lambda: os.environ.get("CMS_APP", ""),
        show_default="CMS_APP env var",
        help="CMS instance as MODULE:ATTRIBUTE (e.g. myapp:cms).",
    )(f)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
def main():
    """starlette-cms management commands."""


# ---------------------------------------------------------------------------
# migrate group
# ---------------------------------------------------------------------------


@main.group()
def migrate():
    """Database and schema migration commands."""


@migrate.command("status")
@_app_option
def migrate_status(app_spec: str) -> None:
    """Show pending migrations between the stored version and package version."""
    from starlette_cms import __version__
    from starlette_cms.migrations import MigrationError, MigrationRunner

    if not app_spec:
        raise click.UsageError("Provide --app or set the CMS_APP environment variable.")

    cms = _load_cms(app_spec)
    runner = MigrationRunner(cms)

    # Fetch stored version without running the full lifespan
    stored = asyncio.run(_fetch_stored_version(cms))
    target = __version__

    click.echo(f"Stored version : {stored or '(none)'}")
    click.echo(f"Package version: {target}")

    if stored == target:
        click.echo(click.style("✓ Up to date — no migrations pending.", fg="green"))
        return

    if stored is None:
        click.echo(
            click.style(
                "Fresh database — schema_version will be seeded on first startup.",
                fg="yellow",
            )
        )
        return

    try:
        pending = runner.pending(current_version=stored, target_version=target)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc

    if not pending:
        click.echo(click.style("✓ Up to date — no migrations pending.", fg="green"))
        return

    click.echo(f"\n{len(pending)} pending migration(s):")
    for step in pending:
        click.echo(f"  {step.from_version} → {step.to_version}  [{step.fn.__name__}]")


@migrate.command("run")
@click.option("--dry-run", is_flag=True, help="Show what would run without applying.")
@_app_option
def migrate_run(dry_run: bool, app_spec: str) -> None:
    """Apply pending migrations (or preview with --dry-run)."""
    from starlette_cms import __version__
    from starlette_cms.migrations import MigrationError, MigrationRunner

    if not app_spec:
        raise click.UsageError("Provide --app or set the CMS_APP environment variable.")

    cms = _load_cms(app_spec)
    runner = MigrationRunner(cms)

    stored = asyncio.run(_fetch_stored_version(cms))
    target = __version__

    if stored is None:
        click.echo(
            click.style("Fresh database — run the app once to seed schema_version.", fg="yellow")
        )
        return

    if stored == target:
        click.echo(click.style("✓ Already up to date.", fg="green"))
        return

    try:
        pending = runner.pending(current_version=stored, target_version=target)
    except MigrationError as exc:
        raise click.ClickException(str(exc)) from exc

    if not pending:
        click.echo(click.style("✓ Already up to date.", fg="green"))
        return

    if dry_run:
        click.echo(f"[dry-run] Would apply {len(pending)} migration(s):")
        for step in pending:
            click.echo(f"  {step.from_version} → {step.to_version}  [{step.fn.__name__}]")
        return

    click.echo(f"Applying {len(pending)} migration(s)...")
    asyncio.run(_run_migrations(cms, runner, pending))
    click.echo(click.style(f"✓ Done. Schema is now at {target}.", fg="green"))


# ---------------------------------------------------------------------------
# mcp group
# ---------------------------------------------------------------------------


@main.group()
def mcp():
    """MCP server commands (requires starlette-cms[mcp])."""


@mcp.command("serve")
@click.option(
    "--url",
    required=True,
    help="Base URL of the starlette-cms instance (e.g. https://mysite.com/cms).",
)
@click.option(
    "--api-key",
    default=None,
    envvar="CMS_API_KEY",
    show_default="CMS_API_KEY env var",
    help="API key for Authorization: Bearer header on mutating requests.",
)
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "sse", "streamable-http"]),
    show_default=True,
    help="MCP transport protocol.",
)
def mcp_serve(url: str, api_key: str | None, transport: str) -> None:
    """
    Start the starlette-cms MCP server.

    Connects to the CMS at --url and exposes its document API as agent-callable
    tools.  Run locally; point at a deployed CMS instance over HTTP.

    Examples::

        # Connect to a local dev server
        starlette-cms mcp serve --url http://localhost:8000/cms

        # Connect to production with an API key
        starlette-cms mcp serve --url https://mysite.com/cms --api-key secret
    """
    try:
        from starlette_cms.mcp.server import build_mcp_server
    except ImportError:
        raise click.ClickException(
            "MCP server requires the 'mcp' extra. "
            "Install with: pip install starlette-cms[mcp]"
        )

    server = build_mcp_server(base_url=url.rstrip("/"), api_key=api_key)
    server.run(transport=transport)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


@main.command()
@_app_option
def validate(app_spec: str) -> None:
    """Re-validate all stored documents against the current block schemas."""
    if not app_spec:
        raise click.UsageError("Provide --app or set the CMS_APP environment variable.")

    cms = _load_cms(app_spec)
    errors = asyncio.run(_validate_documents(cms))

    if not errors:
        click.echo(click.style("✓ All documents are valid.", fg="green"))
        return

    click.echo(click.style(f"✗ {len(errors)} document(s) failed validation:", fg="red"))
    for doc_id, doc_type, detail in errors:
        click.echo(f"  [{doc_type}] {doc_id}")
        for err in detail:
            click.echo(f"    - {err}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Async helpers (run via asyncio.run)
# ---------------------------------------------------------------------------


async def _fetch_stored_version(cms: CMS) -> str | None:
    """
    Initialise the DB engine (without the version check) and read
    schema_version from cms_meta.  Returns None if the table is empty.
    """
    from starlette_cms.db import CMSDatabase

    # Build engine + create tables — but skip the mismatch check.
    # We do this by temporarily passing an empty schema_version so
    # CMSDatabase.init() won't raise on a stale DB.
    db = CMSDatabase(database_url=cms.database_url, schema_version="")
    await db.init()
    try:
        from starlette_cms.tables import CMSMeta

        rows = await CMSMeta.select().where(CMSMeta.key == "schema_version").run()
        return rows[0]["value"] if rows else None
    finally:
        await db.close()


async def _run_migrations(cms: CMS, runner, pending) -> None:
    """Open DB, attach to cms._db, run migrations, close."""
    from starlette_cms.db import CMSDatabase

    db = CMSDatabase(database_url=cms.database_url, schema_version="")
    await db.init()
    cms._db = db
    try:
        await runner.run(pending, dry_run=False)
    finally:
        await db.close()
        cms._db = None


async def _validate_documents(cms: CMS) -> list[tuple[str, str, list[str]]]:
    """
    Load all documents and validate each against the registered document model.

    Returns a list of (id, doc_type, [error_messages]) for failures.
    """
    import json

    from pydantic import ValidationError

    from starlette_cms.db import CMSDatabase
    from starlette_cms.tables import CMSDocument

    db = CMSDatabase(database_url=cms.database_url, schema_version="")
    await db.init()
    errors: list[tuple[str, str, list[str]]] = []

    try:
        rows = await CMSDocument.select().run()
        for row in rows:
            doc_id = row["id"]
            doc_type = row["doc_type"]
            body = row.get("body", "{}")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except Exception:
                    body = {}

            model = cms._document_types.get(doc_type)
            if model is None:
                errors.append((doc_id, doc_type, [f"Unknown document type {doc_type!r}"]))
                continue

            try:
                model.model_validate(body)
            except ValidationError as exc:
                error_strs = [
                    f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
                ]
                errors.append((doc_id, doc_type, error_strs))
    finally:
        await db.close()

    return errors
