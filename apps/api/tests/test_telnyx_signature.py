import base64
import time

import nacl.signing
import pytest

from app.telephony.signature import WebhookSignatureError, verify_telnyx


def _setup_key(monkeypatch) -> nacl.signing.SigningKey:
    sk = nacl.signing.SigningKey.generate()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    monkeypatch.setenv("VOICE_TELNYX_WEBHOOK_PUBLIC_KEY", pub_b64)
    from app.core.config import get_settings
    get_settings.cache_clear()
    return sk


def test_verify_ok(monkeypatch):
    sk = _setup_key(monkeypatch)
    body = b'{"data":{"event_type":"call.answered"}}'
    ts = str(int(time.time()))
    sig = base64.b64encode(sk.sign(f"{ts}|".encode() + body).signature).decode()
    verify_telnyx(raw_body=body, signature_b64=sig, timestamp=ts)


def test_verify_bad_sig(monkeypatch):
    sk = _setup_key(monkeypatch)
    body = b"{}"
    ts = str(int(time.time()))
    bad = base64.b64encode(sk.sign(b"someother").signature).decode()
    with pytest.raises(WebhookSignatureError):
        verify_telnyx(raw_body=body, signature_b64=bad, timestamp=ts)


def test_verify_skew(monkeypatch):
    sk = _setup_key(monkeypatch)
    body = b"{}"
    ts = str(int(time.time()) - 999)
    sig = base64.b64encode(sk.sign(f"{ts}|".encode() + body).signature).decode()
    with pytest.raises(WebhookSignatureError):
        verify_telnyx(raw_body=body, signature_b64=sig, timestamp=ts)
