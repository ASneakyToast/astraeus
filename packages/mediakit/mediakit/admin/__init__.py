"""
Admin UI routes for mediakit.

Provides a browser-based interface for uploading and browsing assets.

Requires the ``[admin]`` optional dependency (jinja2 + python-multipart)::

    pip install mediakit[admin]

Usage — the routes are wired automatically in ``MediaKit._build_app`` when
jinja2 is installed.  Mount the parent app at a path prefix::

    app = Starlette(routes=[Mount("/media", app=mk.app)])

Then visit ``/media/admin`` in a browser.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from mediakit.app import MediaKit


# Static files directory is one level up from this file (mediakit/static/)
STATIC_DIR = Path(__file__).parent.parent / "static"


def make_admin_routes(mk: MediaKit) -> list[Route | Mount]:
    """Return admin UI routes for *mk*.

    Requires jinja2 to be installed (``mediakit[admin]``).  Raises
    ``ImportError`` if jinja2 is absent — the caller in ``app.py``
    catches that and silently skips the admin routes.

    :param mk: The :class:`~mediakit.app.MediaKit` instance.
    """
    from jinja2 import Environment, PackageLoader, select_autoescape

    env = Environment(
        loader=PackageLoader("mediakit.admin", "templates"),
        autoescape=select_autoescape(["html"]),
    )

    # ------------------------------------------------------------------
    # Helper: build a 256px square IIIF thumbnail URL for a given key
    # ------------------------------------------------------------------

    def iiif_thumb(key: str, size: str = "256,") -> str:
        """Return the IIIF thumbnail URL for *key* at *size*."""
        return f"/iiif/{key}/square/{size}/0/default.webp"

    # ------------------------------------------------------------------
    # Asset browser — GET /admin
    # ------------------------------------------------------------------

    async def browser(request: Request) -> HTMLResponse:
        """``GET /admin`` — responsive grid of asset thumbnails."""
        params = request.query_params
        try:
            limit = int(params.get("limit", 50))
            offset = int(params.get("offset", 0))
        except ValueError:
            limit, offset = 50, 0

        content_type = params.get("content_type") or None
        tags_param = params.get("tags") or None
        tags = [t.strip() for t in tags_param.split(",")] if tags_param else None
        picker = params.get("picker", "0") == "1"

        assets = await mk.catalog.list_assets(
            limit=limit,
            offset=offset,
            content_type=content_type,
            tags=tags,
        )

        template = env.get_template("browser.html")
        html = template.render(
            assets=assets,
            limit=limit,
            offset=offset,
            content_type_filter=content_type or "",
            tags_filter=tags_param or "",
            picker=picker,
            iiif_thumb=iiif_thumb,
            prev_offset=max(0, offset - limit),
            next_offset=offset + limit,
            has_prev=offset > 0,
            has_next=len(assets) == limit,
        )
        return HTMLResponse(html)

    # ------------------------------------------------------------------
    # Upload page — GET /admin/upload
    # ------------------------------------------------------------------

    async def upload_page(request: Request) -> HTMLResponse:
        """``GET /admin/upload`` — drag-and-drop upload form."""
        picker = request.query_params.get("picker", "0") == "1"
        template = env.get_template("upload.html")
        html = template.render(picker=picker)
        return HTMLResponse(html)

    # ------------------------------------------------------------------
    # Asset detail — GET /admin/assets/{key:path}
    # ------------------------------------------------------------------

    async def asset_detail(request: Request) -> Response:
        """``GET /admin/assets/{key:path}`` — asset detail view."""
        key = request.path_params["key"]
        asset = await mk.catalog.get_asset(key)
        if asset is None:
            template = env.get_template("base.html")
            html = template.render(title="Not Found", content="<p>Asset not found.</p>")
            return HTMLResponse(html, status_code=404)

        picker = request.query_params.get("picker", "0") == "1"
        template = env.get_template("detail.html")
        html = template.render(
            asset=asset,
            picker=picker,
            iiif_thumb=iiif_thumb,
        )
        return HTMLResponse(html)

    # ------------------------------------------------------------------
    # Metadata update — POST /admin/assets/{key:path}
    # ------------------------------------------------------------------

    async def update_asset(request: Request) -> Response:
        """``POST /admin/assets/{key:path}`` — handle metadata form submit."""
        from mediakit.auth import require_auth

        if (err := await require_auth(request, mk)) is not None:
            return err

        key = request.path_params["key"]

        form = await request.form()
        _alt_text_raw = form.get("alt_text")
        alt_text: str | None = str(_alt_text_raw) if isinstance(_alt_text_raw, str) and _alt_text_raw else None
        _tags_raw = form.get("tags")
        tags_raw: str = str(_tags_raw) if isinstance(_tags_raw, str) else ""
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        await mk.catalog.update_asset(key, alt_text=alt_text, tags=tags)

        return RedirectResponse(f"/admin/assets/{key}", status_code=303)

    # ------------------------------------------------------------------
    # Route list
    # ------------------------------------------------------------------

    return [
        Route("/admin", endpoint=browser, methods=["GET"]),
        Route("/admin/upload", endpoint=upload_page, methods=["GET"]),
        Route("/admin/assets/{key:path}", endpoint=asset_detail, methods=["GET"]),
        Route("/admin/assets/{key:path}", endpoint=update_asset, methods=["POST"]),
        Mount("/admin/static", app=StaticFiles(directory=str(STATIC_DIR)), name="admin-static"),
    ]
