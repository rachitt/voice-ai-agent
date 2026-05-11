"""Telnyx Ed25519 webhook signature verification.

Telnyx signs `${timestamp}|${raw_body}` with their per-account Ed25519 key and
sends the signature in base64. We hold their public key in settings.
"""
from __future__ import annotations

import base64
import time

import nacl.exceptions
import nacl.signing

from app.core.config import get_settings

# Reject anything older than 5 minutes
MAX_SKEW_S = 300


class WebhookSignatureError(Exception):
    pass


def _public_key() -> nacl.signing.VerifyKey:
    pem_or_b64 = get_settings().telnyx_webhook_public_key
    if not pem_or_b64:
        raise WebhookSignatureError("telnyx_webhook_public_key not configured")
    try:
        raw = base64.b64decode(pem_or_b64)
    except Exception as exc:
        raise WebhookSignatureError("invalid public key encoding") from exc
    if len(raw) != 32:
        raise WebhookSignatureError("public key must be 32 raw bytes (base64-encoded)")
    return nacl.signing.VerifyKey(raw)


def verify_telnyx(
    *,
    raw_body: bytes,
    signature_b64: str | None,
    timestamp: str | None,
    now: float | None = None,
) -> None:
    if not signature_b64 or not timestamp:
        raise WebhookSignatureError("missing signature or timestamp header")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise WebhookSignatureError("non-integer timestamp") from exc

    skew = abs((now if now is not None else time.time()) - ts)
    if skew > MAX_SKEW_S:
        raise WebhookSignatureError(f"timestamp skew {skew:.0f}s exceeds {MAX_SKEW_S}s")

    try:
        sig = base64.b64decode(signature_b64)
    except Exception as exc:
        raise WebhookSignatureError("invalid signature encoding") from exc

    signed = f"{timestamp}|".encode() + raw_body
    try:
        _public_key().verify(signed, sig)
    except nacl.exceptions.BadSignatureError as exc:
        raise WebhookSignatureError("bad signature") from exc
