"""Editor routes — /shell, /embed.js, and /static/*"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from starlette_editor.app import Editor

STATIC_DIR = pathlib.Path(__file__).parent / "static"


def make_editor_routes(editor: Editor) -> list:
    """Return the routes for the editor sub-application.

    Routes:
      GET /shell     — HTML shell page (injects JS config, loads static assets)
      GET /embed.js  — Public embed script for live editing on static sites
      /static/*      — Static file serving (editor.css, editor.js, embed.js)
    """

    async def shell_endpoint(request: Request) -> HTMLResponse:
        """Serve the single-page editor shell."""
        # Honour optional auth guard
        if editor.auth is not None:
            allowed = editor.auth(request)
            # Support both sync and async auth callables
            if hasattr(allowed, "__await__"):
                allowed = await allowed
            if not allowed:
                return HTMLResponse("Unauthorized", status_code=401)

        mount = editor.mount_path.rstrip("/")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>CMS Editor</title>
  <link rel="stylesheet" href="{mount}/static/editor.css" />
</head>
<body>
  <div id="app"></div>

  <!-- Editor bootstrap config — injected server-side -->
  <script>
  window.__EDITOR_CONFIG__ = {{
    cmsBase: "",
    apiKey: {_js_string(editor.cms.api_key)},
    mountPath: {_js_string(mount)},
    mediaBase: {_js_string(editor.media_base)}
  }};
  </script>

  <script src="{mount}/static/editor.js"></script>
</body>
</html>"""
        return HTMLResponse(html)

    async def embed_js_endpoint(request: Request) -> Response:
        """Serve the embed script for live editing on static sites.

        No auth required — the script itself is public. It checks
        authentication at runtime via /api/auth/me and exits silently
        for unauthenticated visitors.
        """
        embed_path = STATIC_DIR / "embed.js"
        if not embed_path.exists():
            return Response("embed.js not built", status_code=404)
        content = embed_path.read_bytes()
        return Response(
            content,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    routes: list = [
        Route("/shell", endpoint=shell_endpoint, methods=["GET"]),
        Route("/embed.js", endpoint=embed_js_endpoint, methods=["GET"]),
    ]

    if STATIC_DIR.exists():
        routes.append(Mount("/static", app=StaticFiles(directory=str(STATIC_DIR))))

    return routes


def _js_string(value: str | None) -> str:
    """Safely encode a Python string value for inline JavaScript."""
    if value is None:
        return "null"
    # Escape characters that would break the JS string literal
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("<", "\\u003c")  # prevent </script> injection
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return f'"{escaped}"'
