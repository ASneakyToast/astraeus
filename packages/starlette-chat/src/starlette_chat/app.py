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
    :param session_db_url: Optional SQLite URL for a separate sessions/messages DB
        (e.g. ``sqlite:///./chat.db``).  When set, chat_session and chat_message
        records are stored here instead of the CMS DB — system_prompt and
        model_config remain in the CMS.  When ``None`` (default), all records go
        through the CMS HTTP API as before.
    :param session_secret: Optional HMAC secret used to validate ``cms_session``
        cookies for browser-based auth.  When set, authenticated editor users
        can use the chat API without any credentials in the page HTML — the
        browser sends the session cookie automatically.  Must match the
        ``session_secret`` configured on the CMS instance.
    :param cors_origins: List of allowed CORS origins (e.g. ``["http://localhost:4321"]``).
        Required when the chat sub-app is served from a different origin than the
        frontend (cross-origin cookie auth needs ``allow_credentials=True``).
        Pass the same list you give to :class:`~starlette_cms.app.CMS`.
    :param checkpointer: LangGraph checkpointer for the agent's turn-to-turn
        memory.  Defaults to an in-process ``MemorySaver`` (resets on restart).
        Pass a ``SqliteSaver`` or ``PostgresSaver`` for durable memory.
    """

    def __init__(
        self,
        cms_base_url: str,
        cms_api_key: str,
        provider: BaseProvider | None = None,
        session_db_url: str | None = None,
        session_secret: str | None = None,
        cors_origins: list[str] | None = None,
        checkpointer: object | None = None,
    ) -> None:
        from langgraph.checkpoint.memory import MemorySaver

        self._cms_base = cms_base_url.rstrip("/")
        self._cms_api_key = cms_api_key
        self._provider = provider
        self._session_db_url = session_db_url
        self._session_secret = session_secret
        self._cors_origins = cors_origins or []
        self._checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self._store = None
        self._app: Starlette | None = None

        if session_db_url:
            from starlette_chat.store import SQLiteSessionStore
            self._store = SQLiteSessionStore(session_db_url)

    @property
    def app(self) -> Starlette:
        """Lazy-initialised Starlette application.  Access triggers route wiring."""
        if self._app is None:
            self._app = self._build_app()
        return self._app

    def _build_app(self) -> Starlette:
        from contextlib import asynccontextmanager

        from starlette.middleware import Middleware
        from starlette.middleware.cors import CORSMiddleware

        from .routes import make_routes

        store = self._store

        @asynccontextmanager
        async def lifespan(app: Starlette):  # type: ignore[type-arg]
            if store is not None:
                await store.init_db()
            yield

        middleware = []
        if self._cors_origins:
            middleware.append(Middleware(
                CORSMiddleware,
                allow_origins=self._cors_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                allow_credentials=True,
            ))

        routes = make_routes(self)
        return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
