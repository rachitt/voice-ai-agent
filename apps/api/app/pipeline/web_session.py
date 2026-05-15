"""Short-lived session tokens for browser web calls and SSE spectators.

WS token: HMAC(secret, "ws:" + call_id) — deterministic, lives for the call.
SSE token: signed payload `sse:{exp}:{call_id}:{org_id}` — TTL-bound (5 min).
Neither requires Redis. Rotation requires rotating webhook_hmac_secret.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from app.core.config import get_settings


def _key() -> bytes:
    return get_settings().webhook_hmac_secret.encode()


def mint_ws_token(call_id: str) -> str:
    return hmac.new(_key(), f"ws:{call_id}".encode(), hashlib.sha256).hexdigest()


def verify_ws_token(call_id: str, token: str) -> bool:
    expected = mint_ws_token(call_id)
    return hmac.compare_digest(expected, token)


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: bytes) -> str:
    return _b64e(hmac.new(_key(), payload, hashlib.sha256).digest())


SSE_TOKEN_TTL_SECONDS = 300


def mint_sse_token(
    call_id: str, org_id: str, ttl_seconds: int = SSE_TOKEN_TTL_SECONDS
) -> tuple[str, int]:
    exp = int(time.time()) + ttl_seconds
    payload = f"sse:{exp}:{call_id}:{org_id}".encode()
    return f"{_b64e(payload)}.{_sign(payload)}", exp


def verify_sse_token(token: str, *, call_id: str) -> str | None:
    """Return org_id if token is valid for call_id and not expired, else None."""
    try:
        p_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    try:
        payload = _b64d(p_b64)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(payload), sig):
        return None
    try:
        parts = payload.decode("utf-8").split(":")
    except UnicodeDecodeError:
        return None
    if len(parts) != 4 or parts[0] != "sse":
        return None
    try:
        exp = int(parts[1])
    except ValueError:
        return None
    if time.time() > exp:
        return None
    if parts[2] != call_id:
        return None
    return parts[3]
