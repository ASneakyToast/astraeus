"""
SQLiteSessionStore — optional separate storage for chat sessions and messages.

When ChatAPI is constructed with ``session_db_url``, sessions and messages are
written here instead of the CMS DB.  system_prompt and model_config are still
fetched from the CMS at session-creation time and snapshotted into each row so
the store is self-contained.

Usage::

    store = SQLiteSessionStore("sqlite:///./chat.db")
    await store.init_db()
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

import aiosqlite

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id          TEXT PRIMARY KEY,
    persona     TEXT,
    doc_ref     TEXT,
    model_name  TEXT,
    temperature REAL,
    max_tokens  INTEGER,
    system_prompt TEXT,
    turn_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    turn_index    INTEGER NOT NULL,
    model_used    TEXT,
    steps_applied INTEGER,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
)
"""


def _parse_path(url: str) -> str:
    """Extract the filesystem path from a ``sqlite:///path`` URL."""
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    return url


def _msg_id() -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "msg-" + "".join(secrets.choice(alphabet) for _ in range(16))


@dataclass
class TurnContext:
    """Data needed at the start of a conversation turn."""

    history: list[dict]        # [{"role": ..., "content": ...}]
    model_name: str
    system_prompt: str
    turn_index: int


class SQLiteSessionStore:
    """Write-through SQLite store for chat sessions and messages.

    :param db_url: SQLite URL or filesystem path, e.g. ``sqlite:///./chat.db``.
    """

    def __init__(self, db_url: str) -> None:
        self._path = _parse_path(db_url)

    async def init_db(self) -> None:
        """Create tables if they don't exist.  Safe to call on every startup."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(_CREATE_SESSIONS)
            await db.execute(_CREATE_MESSAGES)
            await db.commit()

    async def create_session(
        self,
        *,
        session_id: str,
        persona: str,
        doc_ref: str | None,
        model_name: str,
        temperature: float,
        max_tokens: int,
        system_prompt: str,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO chat_sessions
                    (id, persona, doc_ref, model_name, temperature, max_tokens, system_prompt)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, persona, doc_ref, model_name, temperature, max_tokens, system_prompt),
            )
            await db.commit()

    async def get_session(self, session_id: str) -> dict | None:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
            ) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def get_turn_context(self, session_id: str) -> TurnContext | None:
        """Load everything needed at the start of a turn from the local DB."""
        session = await self.get_session(session_id)
        if session is None:
            return None

        messages = await self.list_messages(session_id)
        history = [{"role": m["role"], "content": m["content"]} for m in messages]

        return TurnContext(
            history=history,
            model_name=session.get("model_name") or "claude-sonnet-4-5",
            system_prompt=session.get("system_prompt") or "",
            turn_index=len(messages),
        )

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        turn_index: int,
        *,
        model_used: str | None = None,
        steps_applied: int | None = None,
    ) -> str:
        msg_id = _msg_id()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO chat_messages
                    (id, session_id, role, content, turn_index, model_used, steps_applied)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_id, role, content, turn_index, model_used, steps_applied),
            )
            await db.commit()
        return msg_id

    async def update_turn_count(self, session_id: str, turn_count: int) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE chat_sessions SET turn_count = ? WHERE id = ?",
                (turn_count, session_id),
            )
            await db.commit()

    async def list_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM chat_messages
                WHERE session_id = ?
                ORDER BY turn_index ASC
                LIMIT ?
                """,
                (session_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]
