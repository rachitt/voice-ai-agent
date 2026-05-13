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


def test_verify_missing_headers(monkeypatch):
    _setup_key(monkeypatch)
    with pytest.raises(WebhookSignatureError, match="missing"):
        verify_telnyx(raw_body=b"{}", signature_b64=None, timestamp="123")
    with pytest.raises(WebhookSignatureError, match="missing"):
        verify_telnyx(raw_body=b"{}", signature_b64="abc", timestamp=None)


def test_verify_non_integer_timestamp(monkeypatch):
    _setup_key(monkeypatch)
    with pytest.raises(WebhookSignatureError, match="non-integer"):
        verify_telnyx(raw_body=b"{}", signature_b64="ABC=", timestamp="abc")


def test_verify_invalid_signature_base64(monkeypatch):
    _setup_key(monkeypatch)
    ts = str(int(time.time()))
    with pytest.raises(WebhookSignatureError, match="signature encoding"):
        verify_telnyx(raw_body=b"{}", signature_b64="@@@not-base64@@@", timestamp=ts)


def test_public_key_unconfigured(monkeypatch):
    """No public key set → typed error before any decode happens."""
    monkeypatch.setenv("VOICE_TELNYX_WEBHOOK_PUBLIC_KEY", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    ts = str(int(time.time()))
    sig = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(WebhookSignatureError, match="not configured"):
        verify_telnyx(raw_body=b"{}", signature_b64=sig, timestamp=ts)


def test_public_key_invalid_base64(monkeypatch):
    monkeypatch.setenv("VOICE_TELNYX_WEBHOOK_PUBLIC_KEY", "!!!not-base64!!!")
    from app.core.config import get_settings

    get_settings.cache_clear()
    ts = str(int(time.time()))
    sig = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(WebhookSignatureError, match="public key encoding"):
        verify_telnyx(raw_body=b"{}", signature_b64=sig, timestamp=ts)


def test_public_key_wrong_length(monkeypatch):
    # Valid base64 but decodes to non-32-byte value.
    monkeypatch.setenv("VOICE_TELNYX_WEBHOOK_PUBLIC_KEY", base64.b64encode(b"short").decode())
    from app.core.config import get_settings

    get_settings.cache_clear()
    ts = str(int(time.time()))
    sig = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(WebhookSignatureError, match="32 raw bytes"):
        verify_telnyx(raw_body=b"{}", signature_b64=sig, timestamp=ts)
