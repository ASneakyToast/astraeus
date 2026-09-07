"""Tests for the astraeus-portal package."""

from __future__ import annotations

from astraeus_portal import Portal, PortalApp
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# PortalApp tests
# ---------------------------------------------------------------------------


class TestPortalApp:
    def test_minimal(self) -> None:
        app = PortalApp(name="Test", path="/test")
        assert app.name == "Test"
        assert app.path == "/test"
        assert app.description == ""
        assert app.icon == ""

    def test_full(self) -> None:
        app = PortalApp(
            name="Editor",
            path="/editor/shell",
            description="Edit content",
            icon="✏️",
            tags=["content", "editor"],
        )
        assert app.icon == "✏️"
        assert app.tags == ["content", "editor"]


# ---------------------------------------------------------------------------
# Portal tests
# ---------------------------------------------------------------------------


class TestPortal:
    def test_build_app_no_auth(self) -> None:
        """Portal page renders without auth."""
        portal = Portal(
            apps=[
                PortalApp("Editor", "/editor/shell", "Edit content", "✏️"),
                PortalApp("Media", "/media/admin", "Manage media", "🖼️"),
            ],
            title="Test Portal",
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "text/html; charset=utf-8"
            assert "Test Portal" in resp.text
            assert "Editor" in resp.text
            assert "Media" in resp.text
            assert "/editor/shell" in resp.text
            assert "/media/admin" in resp.text

    def test_empty_apps_shows_helpful_message(self) -> None:
        """Empty apps list shows the 'no apps registered' empty state."""
        portal = Portal(apps=[])
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert "No apps registered" in resp.text
            assert "PortalApp" in resp.text  # hints about usage

    def test_header_links(self) -> None:
        """Header links are rendered."""
        portal = Portal(
            apps=[PortalApp("Test", "/test")],
            header_links={"Docs": "https://docs.example.com", "GitHub": "https://github.com"},
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "docs.example.com" in resp.text
            assert "github.com" in resp.text

    def test_docs_url_in_footer(self) -> None:
        """Docs URL appears in footer."""
        portal = Portal(
            apps=[PortalApp("Test", "/test")],
            docs_url="https://docs.example.com",
            github_url="https://github.com/example/repo",
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "docs.example.com" in resp.text
            assert "github.com/example/repo" in resp.text
            assert "astraeus-portal" in resp.text  # version

    def test_titles_and_descriptions_rendered(self) -> None:
        """App titles and descriptions appear in cards."""
        portal = Portal(
            apps=[
                PortalApp("Editor", "/editor/shell", "Create and edit documents"),
            ],
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "Create and edit documents" in resp.text

    def test_package_info_section(self) -> None:
        """Package info section is rendered when show_package_info is True (default)."""
        portal = Portal(apps=[PortalApp("Test", "/test")])
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            # Should show at least itself
            assert "astraeus-portal" in resp.text

    def test_package_info_disabled(self) -> None:
        """Package info section is hidden when show_package_info is False."""
        portal = Portal(apps=[PortalApp("Test", "/test")], show_package_info=False)
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "Installed Packages" not in resp.text

    def test_tags_rendered(self) -> None:
        """Tags are rendered on the card."""
        portal = Portal(
            apps=[
                PortalApp("Editor", "/editor/shell", tags=["content", "editor"]),
            ],
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "content" in resp.text
            assert "editor" in resp.text


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestPortalAuth:
    def test_auth_blocked(self) -> None:
        """Unauthenticated request redirects to login."""
        portal = Portal(
            apps=[PortalApp("Test", "/test")],
            auth=lambda r: False,
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/", follow_redirects=False)
            assert resp.status_code == 302
            assert "/api/auth/login" in resp.headers["location"]

    def test_auth_allowed(self) -> None:
        """Authenticated request serves the page."""
        portal = Portal(
            apps=[PortalApp("Test", "/test")],
            auth=lambda r: True,
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert resp.status_code == 200
            assert "Test" in resp.text


# ---------------------------------------------------------------------------
# Keyboard nav JS tests (rendered, not runtime)
# ---------------------------------------------------------------------------


class TestKeyboardNav:
    def test_keyboard_nav_script_present(self) -> None:
        """Keyboard navigation JS snippet is included in the page."""
        portal = Portal(
            apps=[
                PortalApp("A", "/a"),
                PortalApp("B", "/b"),
                PortalApp("C", "/c"),
            ],
        )
        app = Starlette(routes=[Mount("/", app=portal.app)])

        with TestClient(app) as client:
            resp = client.get("/")
            assert "keydown" in resp.text
            assert "cards[n - 1].click()" in resp.text
