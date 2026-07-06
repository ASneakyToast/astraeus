"""
Session ID generation helpers for starlette-chat.
"""

from __future__ import annotations

import secrets
import string


def generate_session_slug() -> str:
    """Return a URL-safe random slug for chat session documents.

    Generates a 16-character alphanumeric ID using ``secrets.choice`` for
    cryptographic quality randomness::

        >>> slug = generate_session_slug()
        >>> slug.startswith("chat-session-")
        True
        >>> len(slug)
        29
    """
    alphabet = string.ascii_lowercase + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(16))
    return f"chat-session-{random_part}"
