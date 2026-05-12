"""verify_sse_token — every rejection branch."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from app.core.config import get_settings
from app.pipeline import web_session as ws


def test_sse_round_trip_ok():
    token, exp = ws.mint_sse_token("call_a", "org_a", ttl_seconds=10)
    assert ws.verify_sse_token(token, call_id="call_a") == "org_a"
    assert exp > int(time.time())


def test_sse_returns_none_when_no_dot_separator():
    assert ws.verify_sse_token("nodothere", call_id="call_a") is None


def test_sse_returns_none_on_undecodable_payload():
    """First segment not valid base64 → b64 decode raises → None."""
    assert ws.verify_sse_token("!!!.sig", call_id="call_a") is None


def test_sse_returns_none_on_bad_signature():
    token, _ = ws.mint_sse_token("call_a", "org_a")
    payload_b64 = token.split(".")[0]
    tampered = f"{payload_b64}.{'A' * 43}"
    assert ws.verify_sse_token(tampered, call_id="call_a") is None


def test_sse_returns_none_on_non_utf8_payload(monkeypatch):
    raw = b"\xff\xfe\xfd\xfc"  # invalid utf-8
    key = get_settings().webhook_hmac_secret.encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(key, raw, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    token = f"{base64.urlsafe_b64encode(raw).rstrip(b'=').decode()}.{sig}"
    assert ws.verify_sse_token(token, call_id="call_a") is None


def test_sse_returns_none_on_wrong_format():
    """Three-part payload (missing one segment) → wrong length."""
    payload = b"sse:9999999999:call_a"  # only 3 parts
    key = get_settings().webhook_hmac_secret.encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(key, payload, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    token = f"{base64.urlsafe_b64encode(payload).rstrip(b'=').decode()}.{sig}"
    assert ws.verify_sse_token(token, call_id="call_a") is None


def test_sse_returns_none_on_non_int_exp():
    payload = b"sse:notanumber:call_a:org_a"
    key = get_settings().webhook_hmac_secret.encode()
    sig = base64.urlsafe_b64encode(
        hmac.new(key, payload, hashlib.sha256).digest()
    ).rstrip(b"=").decode()
    token = f"{base64.urlsafe_b64encode(payload).rstrip(b'=').decode()}.{sig}"
    assert ws.verify_sse_token(token, call_id="call_a") is None


def test_sse_returns_none_when_expired():
    token, _ = ws.mint_sse_token("call_a", "org_a", ttl_seconds=-1)
    assert ws.verify_sse_token(token, call_id="call_a") is None


def test_sse_returns_none_when_call_id_mismatch():
    token, _ = ws.mint_sse_token("call_a", "org_a")
    assert ws.verify_sse_token(token, call_id="call_b") is None
