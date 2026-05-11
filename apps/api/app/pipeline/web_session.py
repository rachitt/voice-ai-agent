"""Short-lived WS session token for browser web calls.

Token = HMAC(webhook_hmac_secret, "ws:" + call_id). Deterministic — no Redis
required. Bind to call_id only; rotation requires rotating the HMAC secret.
"""
from __future__ import annotations

import hashlib
import hmac

from app.core.config import get_settings


def _key() -> bytes:
    return get_settings().webhook_hmac_secret.encode()


def mint_ws_token(call_id: str) -> str:
    return hmac.new(_key(), f"ws:{call_id}".encode(), hashlib.sha256).hexdigest()


def verify_ws_token(call_id: str, token: str) -> bool:
    expected = mint_ws_token(call_id)
    return hmac.compare_digest(expected, token)
