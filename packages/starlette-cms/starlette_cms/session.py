"""
Stateless HMAC-SHA256 session tokens for browser-based auth.

Token format: base64url(payload_json).base64url(signature)
where signature = HMAC-SHA256(secret, payload_json)

Usage::

    token = generate_session_token("joel", secret="my-secret")
    user_id = validate_session_token(token, secret="my-secret")
    # user_id == "joel" if valid, None if expired or tampered
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    # Re-add padding
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def generate_session_token(
    user_id: str,
    secret: str,
    ttl_seconds: int = 86400,
) -> str:
    """
    Generate a stateless HMAC-SHA256 session token.

    :param user_id: The subject identifier to embed in the token.
    :param secret: HMAC signing secret.
    :param ttl_seconds: Token lifetime in seconds (default 86400 = 24 h).
    :returns: A ``base64url(payload).base64url(sig)`` string.
    """
    iat = int(time.time())
    payload = {"sub": user_id, "iat": iat, "exp": iat + ttl_seconds}
    payload_json = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), payload_json, hashlib.sha256).digest()
    return f"{_b64url_encode(payload_json)}.{_b64url_encode(sig)}"


def validate_session_token(token: str, secret: str) -> str | None:
    """
    Validate a session token and return the user ID if valid.

    Returns ``None`` if the token is malformed, has an invalid signature,
    or has expired.

    :param token: Token string produced by :func:`generate_session_token`.
    :param secret: HMAC signing secret (must match the one used to generate).
    :returns: ``payload["sub"]`` on success, ``None`` on any failure.
    """
    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts
    try:
        payload_bytes = _b64url_decode(payload_b64)
        given_sig = _b64url_decode(sig_b64)
    except Exception:
        return None

    expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, given_sig):
        return None

    try:
        payload = json.loads(payload_bytes)
    except Exception:
        return None

    if payload.get("exp", 0) <= time.time():
        return None

    return payload.get("sub")
