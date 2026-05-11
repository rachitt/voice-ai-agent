"""Google OAuth flow: login redirect, callback (with mocked Google), me, logout."""
from __future__ import annotations

import pytest

from app.core import config as cfg
from app.core.sessions import mint_session, verify_session
from app.routers import auth_oauth as oauth_mod


@pytest.fixture(autouse=True)
def _enable_oauth(monkeypatch):
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_SECRET", "test-client-secret")
    yield
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_redirects_to_google_with_state_cookie(client):
    r = await client.get("/v1/auth/login/google", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in loc
    assert "state=" in loc
    assert "voice_oauth_state" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_callback_rejects_missing_state(client):
    r = await client.get("/v1/auth/callback/google?code=abc", follow_redirects=False)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(client):
    r = await client.get(
        "/v1/auth/callback/google?code=abc&state=xxx",
        cookies={"voice_oauth_state": "yyy"},
        follow_redirects=False,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_happy_path_creates_user_and_sets_cookie(client, monkeypatch):
    # Mock httpx.AsyncClient used inside the callback
    class _Resp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = "ok"

        def json(self):
            return self._payload

    class _HTTP:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, **kw):
            assert "oauth2.googleapis.com/token" in url
            return _Resp(200, {"access_token": "tok-abc"})

        async def get(self, url, headers=None, **kw):
            assert "userinfo" in url
            return _Resp(200, {
                "sub": "g-12345",
                "email": "user@example.com",
                "name": "Test User",
                "picture": "https://lh3.googleusercontent.com/x",
            })

    monkeypatch.setattr(oauth_mod, "httpx", type("X", (), {"AsyncClient": _HTTP}))

    r = await client.get(
        "/v1/auth/callback/google?code=goodcode&state=match",
        cookies={"voice_oauth_state": "match"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "voice_session=" in set_cookie


@pytest.mark.asyncio
async def test_me_returns_user_for_valid_session(client, db_session):
    from app.db import models

    org = models.Org(name="Acme", slug="acme-oauth")
    db_session.add(org)
    await db_session.flush()
    user = models.User(
        org_id=org.id, email="z@example.com", name="Z", google_sub="g-z"
    )
    db_session.add(user)
    await db_session.commit()

    token = mint_session(user.id, org.id)
    r = await client.get("/v1/auth/me", cookies={"voice_session": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "z@example.com"
    assert body["org"]["slug"] == "acme-oauth"


@pytest.mark.asyncio
async def test_me_401_without_cookie(client):
    r = await client.get("/v1/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_401_invalid_cookie(client):
    r = await client.get("/v1/auth/me", cookies={"voice_session": "garbage"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(client):
    r = await client.post("/v1/auth/logout")
    assert r.status_code == 200
    assert "voice_session=" in r.headers.get("set-cookie", "")
    # Cookie deletion sets max-age=0 / expires in past
    assert "Max-Age=0" in r.headers["set-cookie"] or "expires=" in r.headers["set-cookie"].lower()


def test_session_roundtrip():
    tok = mint_session("usr_x", "org_y")
    claims = verify_session(tok)
    assert claims == {"sub": "usr_x", "org": "org_y"}


def test_session_rejects_tampered():
    tok = mint_session("usr_x", "org_y")
    bad = tok[:-3] + "AAA"
    assert verify_session(bad) is None
