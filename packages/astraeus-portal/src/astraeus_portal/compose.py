"""
Compose function — wire Astraeus packages together into a single Starlette app
with an auto-populated portal at the root.

Usage::

    from astraeus_portal import compose_app

    app = compose_app(
        cms=cms,
        editor=editor,
        media=media,
        chat=chat,
        gateways=gateway_admin,
    )
    # → Portal at / with cards for Editor, Media, Gateways, Chat
    #   CMS at /cms, Editor at /editor, Media at /media, etc.

All arguments are optional — include only the components you use.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount

from astraeus_portal.app import PortalApp

# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------


def compose_app(
    *,
    # Astraeus components
    cms: Any | None = None,
    editor: Any | None = None,
    media: Any | None = None,
    chat: Any | None = None,
    gateways: Any | None = None,
    # Custom extra apps
    extra_apps: list | None = None,
    # Portal configuration
    portal_title: str = "Astraeus",
    docs_url: str | None = None,
    github_url: str | None = None,
    portal_auth: Any | None = None,
    header_links: dict[str, str] | None = None,
    # Mount path overrides
    cms_mount: str = "/cms",
    editor_mount: str = "/editor",
    media_mount: str = "/media",
    chat_mount: str = "/chat",
    gateways_mount: str = "/gateways",
    portal_mount: str = "/",
    # Debug / verbose
    debug: bool = False,
) -> Starlette:
    """Compose Astraeus packages into a single ready-to-use Starlette app.

    Each component is mounted at its conventional path and a :class:`Portal`
    page is added at *portal_mount* (default: ``/``) with auto-populated
    app cards.

    Lifespans are composed automatically — each component that provides a
    ``lifespan_context`` is entered in order.
    """
    from astraeus_portal.app import Portal
    from astraeus_portal.compose import (
        _build_portal_apps,
        _component_mounts,
        _resolve_lifespan,
    )

    # 1. Build portal app list from components
    apps = _build_portal_apps(
        cms=cms,
        editor=editor,
        media=media,
        chat=chat,
        gateways=gateways,
        extra_apps=extra_apps,
        cms_mount=cms_mount,
        editor_mount=editor_mount,
        media_mount=media_mount,
        chat_mount=chat_mount,
        gateways_mount=gateways_mount,
    )

    # 2. Create portal
    portal = Portal(
        apps=apps,
        title=portal_title,
        docs_url=docs_url,
        github_url=github_url,
        auth=portal_auth,
        show_package_info=True,
    )

    # 3. Build router mounts
    routes: list = []

    portal_routes = _component_mounts(
        cms=cms,
        editor=editor,
        media=media,
        chat=chat,
        gateways=gateways,
        cms_mount=cms_mount,
        editor_mount=editor_mount,
        media_mount=media_mount,
        chat_mount=chat_mount,
        gateways_mount=gateways_mount,
    )
    routes.extend(portal_routes)

    # Portal itself
    routes.append(Mount(portal_mount, app=portal.app))

    # 4. Compose lifespan
    lifespan = _resolve_lifespan(cms=cms, media=media)

    if debug:
        print("=== Astraeus compose_app ===")
        for r in routes:
            print(f"  {r.path}" if hasattr(r, "path") else f"  {r}")
        print(f"  Portal apps: {[a.name for a in apps]}")

    return Starlette(routes=routes, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_portal_apps(
    *,
    cms: Any = None,
    editor: Any = None,
    media: Any = None,
    chat: Any = None,
    gateways: Any = None,
    extra_apps: list[PortalApp] | None = None,
    cms_mount: str = "/cms",
    editor_mount: str = "/editor",
    media_mount: str = "/media",
    chat_mount: str = "/chat",
    gateways_mount: str = "/gateways",
) -> list[PortalApp]:
    """Build the list of PortalApp entries from provided components."""
    apps: list[PortalApp] = []

    if cms:
        apps.append(
            PortalApp(
                name="CMS API",
                path=f"{cms_mount}/api/documents",
                description="REST API endpoint listing all content documents",
                icon="📡",
                tags=["api"],
            )
        )

    if editor:
        apps.append(
            PortalApp(
                name="Editor",
                path=f"{editor_mount}/shell",
                description="Create and edit content documents with the ProseMirror visual editor",
                icon="✏️",
                tags=["content"],
            )
        )

    if media:
        apps.append(
            PortalApp(
                name="Media",
                path=f"{media_mount}/admin",
                description="Browse, upload, and manage media assets",
                icon="🖼️",
                tags=["media"],
            )
        )

    if gateways:
        apps.append(
            PortalApp(
                name="Gateways",
                path=f"{gateways_mount}/shell",
                description="Sync data from external services into the CMS",
                icon="🔄",
                tags=["data"],
            )
        )

    if chat:
        apps.append(
            PortalApp(
                name="Chat",
                path=f"{chat_mount}/shell",
                description="AI-powered editing assistant with live collab",
                icon="💬",
                tags=["ai"],
            )
        )

    if extras := (extra_apps or []):
        apps.extend(extras)

    return apps


def _component_mounts(
    *,
    cms: Any = None,
    editor: Any = None,
    media: Any = None,
    chat: Any = None,
    gateways: Any = None,
    cms_mount: str = "/cms",
    editor_mount: str = "/editor",
    media_mount: str = "/media",
    chat_mount: str = "/chat",
    gateways_mount: str = "/gateways",
) -> list:
    """Build Starlette Mount routes for each provided component."""
    routes: list = []

    if cms:
        routes.append(Mount(cms_mount, app=_get_app(cms)))

    if editor:
        routes.append(Mount(editor_mount, app=_get_app(editor)))

    if media:
        routes.append(Mount(media_mount, app=_get_app(media)))

    if chat:
        routes.append(Mount(chat_mount, app=_get_app(chat)))

    if gateways:
        routes.append(Mount(gateways_mount, app=_get_app(gateways)))

    return routes


def _get_app(component: Any) -> Any:
    """Get the ASGI app from a component, supporting both ``.app`` property
    and direct app instances."""
    if hasattr(component, "app"):
        return component.app
    return component


def _resolve_lifespan(
    *,
    cms: Any = None,
    media: Any = None,
) -> Any:
    """Compose lifespans from multiple components into a single lifespan."""
    lifespan_ctxs: list = []

    if cms is not None and hasattr(cms, "lifespan_context"):
        lifespan_ctxs.append(cms.lifespan_context)
    if media is not None and hasattr(media, "lifespan_context"):
        lifespan_ctxs.append(media.lifespan_context)

    if not lifespan_ctxs:
        return None

    @contextlib.asynccontextmanager
    async def combined_lifespan(app: Any) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for ctx in lifespan_ctxs:
                await stack.enter_async_context(ctx(app))
            yield

    return combined_lifespan
