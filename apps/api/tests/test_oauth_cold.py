"""auth_oauth cold paths: misconfig, token/userinfo errors, upsert branches."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core import config as cfg
from app.core.sessions import mint_session
from app.db import models
from app.routers import auth_oauth as oauth_mod


class _Resp:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "ok"):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _stub_httpx(monkeypatch, *, token: _Resp, user: _Resp):
    class _HTTP:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, data=None, **kw):
            return token

        async def get(self, url, headers=None, **kw):
            return user

    monkeypatch.setattr(oauth_mod, "httpx", type("X", (), {"AsyncClient": _HTTP}))


@pytest.fixture
def oauth_configured(monkeypatch):
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_ID", "id")
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    yield
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_login_503_when_oauth_unconfigured(client, monkeypatch):
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_ID", "")
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_SECRET", "")
    r = await client.get("/v1/auth/login/google", follow_redirects=False)
    assert r.status_code == 503
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_callback_rejects_missing_code(client, oauth_configured):
    r = await client.get(
        "/v1/auth/callback/google?state=x",
        cookies={"voice_oauth_state": "x"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "missing code" in r.json()["detail"]


@pytest.mark.asyncio
async def test_callback_502_on_token_exchange_failure(client, oauth_configured, monkeypatch):
    _stub_httpx(monkeypatch, token=_Resp(400, text="bad"), user=_Resp(200, {}))
    r = await client.get(
        "/v1/auth/callback/google?code=c&state=s",
        cookies={"voice_oauth_state": "s"},
        follow_redirects=False,
    )
    assert r.status_code == 502
    assert "token exchange" in r.json()["detail"]


@pytest.mark.asyncio
async def test_callback_502_when_token_response_missing_access_token(
    client, oauth_configured, monkeypatch
):
    _stub_httpx(monkeypatch, token=_Resp(200, {"no_access": True}), user=_Resp(200, {}))
    r = await client.get(
        "/v1/auth/callback/google?code=c&state=s",
        cookies={"voice_oauth_state": "s"},
        follow_redirects=False,
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_callback_502_on_userinfo_failure(client, oauth_configured, monkeypatch):
    _stub_httpx(
        monkeypatch,
        token=_Resp(200, {"access_token": "t"}),
        user=_Resp(500, text="upstream"),
    )
    r = await client.get(
        "/v1/auth/callback/google?code=c&state=s",
        cookies={"voice_oauth_state": "s"},
        follow_redirects=False,
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_callback_502_when_userinfo_missing_sub_email(
    client, oauth_configured, monkeypatch
):
    _stub_httpx(
        monkeypatch,
        token=_Resp(200, {"access_token": "t"}),
        user=_Resp(200, {"name": "anon"}),
    )
    r = await client.get(
        "/v1/auth/callback/google?code=c&state=s",
        cookies={"voice_oauth_state": "s"},
        follow_redirects=False,
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_me_401_when_user_row_deleted(client, db_session):
    org = models.Org(name="O", slug="me-gone")
    db_session.add(org)
    await db_session.flush()
    user = models.User(
        org_id=org.id, email="x@y.z", google_sub="g-1", last_login_at=datetime.now(UTC)
    )
    db_session.add(user)
    await db_session.commit()
    cookie_value = mint_session(user.id, org.id)
    await db_session.delete(user)
    await db_session.commit()
    r = await client.get("/v1/auth/me", cookies={"voice_session": cookie_value})
    assert r.status_code == 401
    assert "user gone" in r.json()["detail"]


@pytest.mark.asyncio
async def test_upsert_user_updates_existing_google_sub_row(db_session):
    org = models.Org(name="O", slug="up-gs")
    db_session.add(org)
    await db_session.flush()
    existing = models.User(
        org_id=org.id,
        email="dup@example.com",
        google_sub="g-existing",
        last_login_at=datetime(2020, 1, 1, tzinfo=UTC),
        name=None,
    )
    db_session.add(existing)
    await db_session.commit()

    out = await oauth_mod._upsert_user(
        db_session,
        info={
            "sub": "g-existing",
            "email": "dup@example.com",
            "name": "Real Name",
            "picture": "https://pic/x",
        },
    )
    assert out.id == existing.id
    assert out.name == "Real Name"
    assert out.avatar_url == "https://pic/x"
    assert out.last_login_at > datetime(2020, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_upsert_user_binds_google_sub_to_email_match(db_session):
    org = models.Org(name="O", slug="up-em")
    db_session.add(org)
    await db_session.flush()
    existing = models.User(
        org_id=org.id, email="byemail@example.com", last_login_at=datetime.now(UTC)
    )
    db_session.add(existing)
    await db_session.commit()

    out = await oauth_mod._upsert_user(
        db_session,
        info={
            "sub": "g-new",
            "email": "byemail@example.com",
            "name": "Em User",
            "picture": "https://pic/em",
        },
    )
    assert out.id == existing.id
    assert out.google_sub == "g-new"
    assert out.name == "Em User"


@pytest.mark.asyncio
async def test_upsert_user_provisions_unique_slug_on_collision(db_session, monkeypatch):
    """When the base slug is taken, the upsert appends a hex suffix."""
    org = models.Org(name="taken", slug="newuser")
    db_session.add(org)
    await db_session.commit()

    out = await oauth_mod._upsert_user(
        db_session,
        info={"sub": "g-z", "email": "newuser@example.com", "name": "NU"},
    )
    assert out.email == "newuser@example.com"
    # New org slug is base-XXXX, not "newuser"
    new_org = await db_session.get(models.Org, out.org_id)
    assert new_org.slug != "newuser"
    assert new_org.slug.startswith("newuser-")


def test_slugify_handles_special_chars_and_caps():
    assert oauth_mod._slugify("Hello World!") == "hello-world"
    assert oauth_mod._slugify("!!!") == "user"
    assert oauth_mod._slugify("A" * 80).startswith("a")
    assert len(oauth_mod._slugify("A" * 80)) <= 60


def test_secure_cookie_off_in_dev(monkeypatch):
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENV", "dev")
    assert oauth_mod._secure_cookie() is False
    cfg.get_settings.cache_clear()


def test_secure_cookie_on_in_prod(monkeypatch):
    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENV", "prod")
    assert oauth_mod._secure_cookie() is True
    cfg.get_settings.cache_clear()
