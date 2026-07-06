"""Session auth endpoints — /api/auth/login, /api/auth/logout, /api/auth/me"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bcrypt
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from starlette_cms.session import generate_session_token, validate_session_token

if TYPE_CHECKING:
    from starlette_cms.app import CMS

_SESSION_COOKIE = "cms_session"
_COOKIE_MAX_AGE = 86400  # 24 hours


def _login_html(error: bool = False, next_url: str = "") -> str:
    error_block = (
        '<p class="error">Invalid username or password.</p>' if error else ""
    )
    next_field = (
        f'<input type="hidden" name="next" value="{next_url}">' if next_url else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CMS Login</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f1117;
      color: #e2e8f0;
      font-family: system-ui, -apple-system, sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }}
    .card {{
      background: #1a1d27;
      border: 1px solid #2d3149;
      border-radius: 12px;
      padding: 2rem;
      width: 100%;
      max-width: 360px;
    }}
    h1 {{
      font-size: 1.25rem;
      font-weight: 600;
      margin-bottom: 1.5rem;
      color: #f8fafc;
    }}
    label {{
      display: block;
      font-size: 0.8rem;
      font-weight: 500;
      color: #94a3b8;
      margin-bottom: 0.4rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    input[type="text"], input[type="password"] {{
      width: 100%;
      padding: 0.6rem 0.75rem;
      background: #0f1117;
      border: 1px solid #2d3149;
      border-radius: 6px;
      color: #e2e8f0;
      font-size: 0.95rem;
      margin-bottom: 1rem;
      outline: none;
      transition: border-color 0.15s;
    }}
    input[type="text"]:focus, input[type="password"]:focus {{
      border-color: #6366f1;
    }}
    button {{
      width: 100%;
      padding: 0.65rem;
      background: #6366f1;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 0.95rem;
      font-weight: 500;
      cursor: pointer;
      transition: background 0.15s;
    }}
    button:hover {{ background: #4f46e5; }}
    .error {{
      color: #f87171;
      font-size: 0.85rem;
      margin-bottom: 1rem;
      padding: 0.5rem 0.75rem;
      background: rgba(248, 113, 113, 0.1);
      border: 1px solid rgba(248, 113, 113, 0.3);
      border-radius: 6px;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>CMS Login</h1>
    {error_block}
    <form method="POST">
      {next_field}
      <label for="username">Username</label>
      <input type="text" id="username" name="username" autocomplete="username" required>
      <label for="password">Password</label>
      <input type="password" id="password" name="password" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
  </div>
</body>
</html>"""


def make_auth_routes(cms: CMS) -> list[Route]:
    """Build and return the session auth routes, closed over ``cms``."""

    async def login_get(request: Request) -> HTMLResponse:
        error = request.query_params.get("error") == "1"
        next_url = request.query_params.get("next", "")
        return HTMLResponse(_login_html(error=error, next_url=next_url))

    async def login_post(request: Request) -> Response:
        if cms.session_secret is None:
            return Response(
                "CMS_SESSION_SECRET not configured",
                status_code=500,
                media_type="text/plain",
            )

        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")
        next_url = form.get("next", "")

        # Build redirect-to-error URL preserving next param
        error_url = "/api/auth/login?error=1"
        if next_url:
            error_url += f"&next={next_url}"

        admin_users = cms.admin_users or {}
        stored_hash = admin_users.get(username)
        if stored_hash is None:
            return RedirectResponse(error_url, status_code=302)

        if not bcrypt.checkpw(password.encode(), stored_hash.encode()):
            return RedirectResponse(error_url, status_code=302)

        # Valid credentials — issue session cookie.
        # Omit Secure flag on plain-http localhost so the browser stores it.
        is_localhost = request.url.hostname in ("localhost", "127.0.0.1", "::1")
        secure_flag = "" if is_localhost else "Secure; "
        token = generate_session_token(username, cms.session_secret)
        cookie = (
            f"{_SESSION_COOKIE}={token}; "
            f"HttpOnly; {secure_flag}SameSite=Lax; "
            f"Max-Age={_COOKIE_MAX_AGE}; Path=/"
        )

        # Validate next URL — allow absolute URLs to localhost (dev Astro server)
        # and any path-only URL starting with "/".
        if next_url and (
            next_url.startswith("/")
            or (is_localhost and next_url.startswith("http://localhost"))
        ):
            redirect_to = next_url
        else:
            redirect_to = "/"

        response = RedirectResponse(redirect_to, status_code=302)
        response.headers["Set-Cookie"] = cookie
        return response

    async def logout(request: Request) -> Response:
        is_localhost = request.url.hostname in ("localhost", "127.0.0.1", "::1")
        secure_flag = "" if is_localhost else "Secure; "
        clear_cookie = (
            f"{_SESSION_COOKIE}=; "
            f"HttpOnly; {secure_flag}SameSite=Lax; "
            f"Max-Age=0; Path=/"
        )
        response = RedirectResponse("/api/auth/login", status_code=302)
        response.headers["Set-Cookie"] = clear_cookie
        return response

    async def me(request: Request) -> JSONResponse:
        token = request.cookies.get(_SESSION_COOKIE)
        result: dict[str, object] = {"authenticated": False}

        if token and cms.session_secret:
            user_id = validate_session_token(token, cms.session_secret)
            if user_id:
                result = {"authenticated": True, "user": user_id}

        response = JSONResponse(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    return [
        Route("/api/auth/login", endpoint=login_get, methods=["GET"]),
        Route("/api/auth/login", endpoint=login_post, methods=["POST"]),
        Route("/api/auth/logout", endpoint=logout, methods=["POST"]),
        Route("/api/auth/me", endpoint=me, methods=["GET"]),
    ]
