"""
ChatAPI — mountable Starlette sub-application for starlette-chat.

Usage::

    from starlette_chat import ChatAPI, register_blocks

    register_blocks(cms)

    chat = ChatAPI(
        cms_base_url="http://localhost:8000/cms",
        cms_api_key="secret",
    )
    app.mount("/chat", app=chat.app)
"""

from __future__ import annotations

from starlette.applications import Starlette

from starlette_chat.providers.base import BaseProvider


class ChatAPI:
    """Mountable Starlette chat sub-application.

    :param cms_base_url: HTTP base URL for the CMS API (e.g. ``http://localhost:8000/cms``).
    :param cms_api_key: API key for CMS authentication.
    :param provider: LLM provider.  Defaults to ``AnthropicProvider()`` when the
        ``anthropic`` extra is installed.  Pass an explicit instance to override.
    """

    def __init__(
        self,
        cms_base_url: str,
        cms_api_key: str,
        provider: BaseProvider | None = None,
    ) -> None:
        self._cms_base = cms_base_url.rstrip("/")
        self._cms_api_key = cms_api_key
        self._provider = provider
        self._app: Starlette | None = None

    @property
    def app(self) -> Starlette:
        """Lazy-initialised Starlette application.  Access triggers route wiring."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        from .routes import make_routes

        routes = make_routes(self)
        return Starlette(routes=routes)
