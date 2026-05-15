"""session_secret is independent from webhook_hmac_secret.

Rotating one MUST NOT invalidate sessions signed by the other, and a
session minted under the legacy `webhook_hmac_secret` MUST keep verifying
until `session_secret` is set.
"""

from __future__ import annotations

import pytest
from jose import jwt

from app.core import config as cfg
from app.core.sessions import ALGORITHM, mint_session, verify_session


@pytest.fixture(autouse=True)
def _reset_settings():
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_backcompat_falls_back_to_webhook_secret(monkeypatch):
    """When session_secret unset, signing+verify use webhook_hmac_secret."""
    monkeypatch.setenv("VOICE_SESSION_SECRET", "")
    monkeypatch.setenv("VOICE_WEBHOOK_HMAC_SECRET", "legacy-shared")
    cfg.get_settings.cache_clear()

    tok = mint_session("u_1", "o_1")
    decoded = jwt.decode(tok, "legacy-shared", algorithms=[ALGORITHM])
    assert decoded["sub"] == "u_1"
    assert verify_session(tok) == {"sub": "u_1", "org": "o_1"}


def test_dedicated_session_secret_signs_with_session_secret(monkeypatch):
    monkeypatch.setenv("VOICE_SESSION_SECRET", "dedicated-session-key")
    monkeypatch.setenv("VOICE_WEBHOOK_HMAC_SECRET", "webhook-only")
    cfg.get_settings.cache_clear()

    tok = mint_session("u_2", "o_2")
    # Verifies with the dedicated key:
    assert jwt.decode(tok, "dedicated-session-key", algorithms=[ALGORITHM])["sub"] == "u_2"
    # Does NOT verify with the webhook key:
    with pytest.raises(Exception):
        jwt.decode(tok, "webhook-only", algorithms=[ALGORITHM])


def test_rotating_webhook_secret_keeps_sessions_valid(monkeypatch):
    """The whole point: changing webhook HMAC must not log everyone out."""
    monkeypatch.setenv("VOICE_SESSION_SECRET", "stable-session-key")
    monkeypatch.setenv("VOICE_WEBHOOK_HMAC_SECRET", "hmac-v1")
    cfg.get_settings.cache_clear()
    tok = mint_session("u_3", "o_3")

    # Rotate ONLY the webhook secret.
    monkeypatch.setenv("VOICE_WEBHOOK_HMAC_SECRET", "hmac-v2")
    cfg.get_settings.cache_clear()
    assert verify_session(tok) == {"sub": "u_3", "org": "o_3"}


def test_rotating_session_secret_invalidates_old_sessions(monkeypatch):
    """And rotating the session secret (only) does revoke old sessions."""
    monkeypatch.setenv("VOICE_SESSION_SECRET", "session-v1")
    monkeypatch.setenv("VOICE_WEBHOOK_HMAC_SECRET", "hmac-stable")
    cfg.get_settings.cache_clear()
    tok = mint_session("u_4", "o_4")

    monkeypatch.setenv("VOICE_SESSION_SECRET", "session-v2")
    cfg.get_settings.cache_clear()
    assert verify_session(tok) is None
