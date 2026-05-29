"""
Authentication helpers for starlette-cms endpoints.

Three auth modes are supported (configured at ``CMS(auth=...)``):

- ``"none"``      — all requests pass
- ``"apikey"``    — ``Authorization: Bearer {api_key}`` header required
- callable        — ``await cms.auth(request)`` must return ``True``

Usage in endpoint handlers::

    result = await require_auth(request, cms)
    if result is not None:
        return result  # 401 JSONResponse
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.requests import Request
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette_cms.app import CMS


async def check_auth(request: Request, cms: CMS) -> bool:
    """
    Return ``True`` if the request is authorised, ``False`` otherwise.

    :param request: The incoming Starlette request.
    :param cms: The CMS instance whose ``auth`` and ``api_key`` settings apply.
    """
    if cms.auth == "none":
        return True

    if cms.auth == "apikey":
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        token = header[len("Bearer ") :]
        return token == cms.api_key

    if callable(cms.auth):
        result = cms.auth(request)
        # Support both sync and async callables
        if hasattr(result, "__await__"):
            return bool(await result)
        return bool(result)

    return False


async def require_auth(request: Request, cms: CMS) -> JSONResponse | None:
    """
    Check auth and return a 401 ``JSONResponse`` on failure, or ``None`` on success.

    Typical usage in a mutating endpoint::

        if (err := await require_auth(request, cms)) is not None:
            return err

    :param request: The incoming Starlette request.
    :param cms: The CMS instance.
    """
    authorised = await check_auth(request, cms)
    if not authorised:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return None
