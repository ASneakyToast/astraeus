"""
gateways CLI — ``gateways sync``, ``gateways list``, ``gateways status``.

Gateway implementations are discovered via Python entry points under the
``starlette_cms_gateways.gateways`` group.  Add this to your
``pyproject.toml``::

    [project.entry-points."starlette_cms_gateways.gateways"]
    my-gateway = "myapp.gateways:MyGateway"

Then register your gateway with its CLI name (the left-hand side of the entry
point) and point at your CMS::

    gateways sync my-gateway \\
        --cms-url https://cms.example.com \\
        --api-key $CMS_API_KEY

All commands that talk to the CMS accept ``--cms-url`` and ``--api-key``
(defaulting to the ``GATEWAYS_CMS_URL`` and ``GATEWAYS_API_KEY`` env vars).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from importlib.metadata import entry_points
from typing import Any

import click
import structlog


# ---------------------------------------------------------------------------
# Logging setup (CLI is an application — it configures structlog directly)
# ---------------------------------------------------------------------------


def _configure_logging(log_level: int) -> None:
    """
    Configure structlog for the gateways CLI.

    Uses ConsoleRenderer on a TTY, JSONRenderer when piped/in CI.
    Called once by the root group via the --verbose/--quiet flags.
    """
    use_console = sys.stdout.isatty()
    final_renderer = (
        structlog.dev.ConsoleRenderer(colors=True)
        if use_console
        else structlog.processors.JSONRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            final_renderer,
        ],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(log_level)

    root = logging.getLogger()
    root.setLevel(log_level)
    if not root.handlers:
        root.addHandler(handler)


# Module-level logger — available after _configure_logging() is called
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _discover_gateways() -> dict[str, Any]:
    """
    Return a dict of ``{entry_point_name: gateway_class}`` for all installed
    gateways registered under ``starlette_cms_gateways.gateways``.
    """
    eps = entry_points(group="starlette_cms_gateways.gateways")
    result: dict[str, Any] = {}
    for ep in eps:
        try:
            cls = ep.load()
            result[ep.name] = cls
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "starlette_cms_gateways.cli.gateway_load_failed",
                gateway=ep.name,
                exc_info=exc,
            )
    return result


def _cms_url_option(f):
    return click.option(
        "--cms-url",
        default=lambda: os.environ.get("GATEWAYS_CMS_URL", ""),
        show_default="GATEWAYS_CMS_URL env var",
        help="Base URL of the starlette-cms instance (e.g. https://cms.example.com).",
    )(f)


def _api_key_option(f):
    return click.option(
        "--api-key",
        default=lambda: os.environ.get("GATEWAYS_API_KEY"),
        show_default="GATEWAYS_API_KEY env var",
        help="API key for Authorization: Bearer header.",
    )(f)


def _require_cms_url(cms_url: str) -> str:
    if not cms_url:
        raise click.UsageError(
            "Provide --cms-url or set the GATEWAYS_CMS_URL environment variable."
        )
    return cms_url.rstrip("/")


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------


@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable DEBUG logging.")
@click.option("-q", "--quiet", is_flag=True, default=False, help="Suppress INFO logs (WARNING+ only).")
@click.pass_context
def main(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """starlette-cms gateway management commands."""
    ctx.ensure_object(dict)
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    _configure_logging(level)


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@main.command("list")
def list_gateways() -> None:
    """List all installed gateways discovered via entry points."""
    gateways = _discover_gateways()
    if not gateways:
        click.echo("No gateways found.")
        click.echo(
            "Register one under [project.entry-points.\"starlette_cms_gateways.gateways\"] "
            "in your pyproject.toml."
        )
        return

    click.echo(f"Installed gateways ({len(gateways)}):")
    for name, cls in sorted(gateways.items()):
        svc = getattr(cls, "service_name", "?")
        bt = getattr(cls, "block_type", "?")
        auto = getattr(cls, "auto_publish", True)
        click.echo(
            f"  {click.style(name, fg='cyan')}  "
            f"service={svc!r}  block={bt!r}  auto_publish={auto}"
        )


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command("status")
@_cms_url_option
@_api_key_option
def status(cms_url: str, api_key: str | None) -> None:
    """Show the last sync state for all gateways (reads the CMS singleton)."""
    cms_url = _require_cms_url(cms_url)

    async def _run() -> None:
        from starlette_cms_gateways.client import CMSClient, CMSError

        client = CMSClient(base_url=cms_url, api_key=api_key)
        try:
            state = await client.get_gateway_status()
        except CMSError as exc:
            raise click.ClickException(str(exc)) from exc
        finally:
            await client.close()

        services = state.get("services") or {}
        if not services:
            click.echo("No sync state recorded yet.")
            return

        for svc_name, svc_data in sorted(services.items()):
            last = svc_data.get("last_synced", "never")
            r = svc_data.get("last_result") or {}
            created = r.get("created", 0)
            updated = r.get("updated", 0)
            skipped = r.get("skipped", 0)
            errors = len(r.get("errors") or [])
            click.echo(
                f"{click.style(svc_name, fg='cyan')}  "
                f"last_synced={last}  "
                f"created={created}  updated={updated}  "
                f"skipped={skipped}  errors={errors}"
            )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@main.command("sync")
@click.argument("gateway_name")
@_cms_url_option
@_api_key_option
@click.option(
    "--full-refresh",
    is_flag=True,
    default=False,
    help="Ignore last-sync timestamp and fetch everything from the source.",
)
def sync(
    gateway_name: str,
    cms_url: str,
    api_key: str | None,
    full_refresh: bool,
) -> None:
    """
    Run a sync for the named gateway.

    GATEWAY_NAME must be a registered entry point under
    starlette_cms_gateways.gateways.
    """
    cms_url = _require_cms_url(cms_url)

    gateways = _discover_gateways()
    if gateway_name not in gateways:
        available = ", ".join(sorted(gateways)) or "(none)"
        raise click.UsageError(
            f"Unknown gateway {gateway_name!r}. Available: {available}"
        )

    gateway_cls = gateways[gateway_name]

    async def _run() -> None:
        from starlette_cms_gateways.client import CMSClient, CMSError

        client = CMSClient(base_url=cms_url, api_key=api_key)
        try:
            gateway = gateway_cls(cms_client=client)
            click.echo(
                f"Syncing {click.style(gateway_name, fg='cyan')} "
                f"({'full refresh' if full_refresh else 'incremental'})…"
            )
            result = await gateway.sync(full_refresh=full_refresh)
        except CMSError as exc:
            raise click.ClickException(str(exc)) from exc
        finally:
            await client.close()

        if result.errors:
            for ref, msg in result.errors:
                logger.warning(
                    "starlette_cms_gateways.sync.item_failed",
                    gateway=gateway_name,
                    import_ref=ref,
                    error=msg,
                )

        status_fg = "red" if result.has_errors else "green"
        click.echo(
            click.style(
                f"✓ Done — created={result.created}  "
                f"updated={result.updated}  skipped={result.skipped}  "
                f"errors={len(result.errors)}",
                fg=status_fg,
            )
        )
        if result.errors:
            click.echo("Errors:")
            for ref, msg in result.errors:
                click.echo(f"  {ref}: {msg}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# register-blocks
# ---------------------------------------------------------------------------


@main.command("register-blocks")
@click.option(
    "--app",
    "app_spec",
    default=lambda: os.environ.get("CMS_APP", ""),
    show_default="CMS_APP env var",
    help="CMS instance as MODULE:ATTRIBUTE (e.g. myapp:cms).",
)
def register_blocks(app_spec: str) -> None:
    """
    Register the gateway_sync_state singleton block on a CMS instance.

    Use this in your startup script or CI pipeline to ensure the
    gateway_sync_state block is registered before running migrations.
    """
    if not app_spec:
        raise click.UsageError("Provide --app or set the CMS_APP environment variable.")

    import importlib
    import sys

    if ":" not in app_spec:
        raise click.UsageError(
            f"Invalid --app value {app_spec!r}. Use MODULE:ATTRIBUTE format."
        )
    module_path, attr = app_spec.rsplit(":", 1)

    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise click.ClickException(f"Cannot import {module_path!r}: {exc}") from exc

    cms = getattr(module, attr, None)
    if cms is None:
        raise click.ClickException(f"{module_path!r} has no attribute {attr!r}.")

    from starlette_cms_gateways.blocks import register

    try:
        register(cms)
        click.echo(
            click.style("✓ gateway_sync_state block registered.", fg="green")
        )
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(str(exc)) from exc
