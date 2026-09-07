"""
Portal — mountable Starlette sub-application for the Astraeus navigation hub.

Usage::

    from astraeus_portal import Portal, PortalApp

    portal = Portal(apps=[
        PortalApp("Editor",   "/editor/shell",   "Create and edit content",  "✏️"),
        PortalApp("Media",    "/media/admin",    "Browse and manage media",  "🖼️"),
        PortalApp("Gateways", "/gateways/shell",  "Sync external data",      "🔄"),
        PortalApp("Chat",     "/chat/shell",     "AI editing assistant",    "💬"),
    ])

    app = Starlette(routes=[Mount("/", app=portal.app)])
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from starlette.applications import Starlette

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# PortalApp — lightweight app descriptor
# ---------------------------------------------------------------------------


@dataclass
class PortalApp:
    """Descriptor for a single app entry on the portal page.

    :param name: Human-readable app name (e.g. "Editor", "Media").
    :param path: URL path to the app's shell page (e.g. "/editor/shell").
    :param description: One-line description shown on the portal card.
    :param icon: Optional emoji or icon character shown beside the name.
    :param tags: Optional list of tag strings for filtering/categorisation.
    """

    name: str
    path: str
    description: str = ""
    icon: str = ""
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Portal — main entry point
# ---------------------------------------------------------------------------


DEFAULT_APPS: list[PortalApp] = []


class Portal:
    """Mountable Starlette sub-application that serves the Astraeus portal page.

    :param apps: List of :class:`PortalApp` descriptors.  The portal displays
        them as a grid of clickable cards.
    :param title: Page title / site name (default ``"Astraeus"``).
    :param docs_url: Optional URL to hosted documentation.
    :param github_url: Optional URL to the repository.
    :param auth: Optional auth callable ``(request) -> bool`` protecting the
        portal page.  Default ``None`` — open access.
    :param login_path: Redirect target for unauthenticated visitors when an
        auth guard is set (defaults to the CMS session-login route).
    :param header_links: Optional dict of ``{label: url}`` shown in the
        navigation header bar.
    :param show_package_info: If ``True``, attempt to import and display
        installed package versions (default ``True``).
    """

    def __init__(
        self,
        *,
        apps: list[PortalApp] | None = None,
        title: str = "Astraeus",
        docs_url: str | None = None,
        github_url: str | None = None,
        auth: Callable | None = None,
        login_path: str = "/api/auth/login",
        header_links: dict[str, str] | None = None,
        show_package_info: bool = True,
    ) -> None:
        self.apps = apps or list(DEFAULT_APPS)
        self.title = title
        self.docs_url = docs_url
        self.github_url = github_url
        self.auth = auth
        self.login_path = login_path
        self.header_links = header_links or {}
        self.show_package_info = show_package_info
        self._app: Starlette | None = None

    @property
    def app(self) -> Starlette:
        """Build and return the Starlette sub-application. Built once on first access."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        from astraeus_portal.routes import make_portal_routes

        return Starlette(routes=make_portal_routes(self))
