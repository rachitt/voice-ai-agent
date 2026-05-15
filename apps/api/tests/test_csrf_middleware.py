"""CSRF double-submit-cookie middleware."""

from __future__ import annotations

import pytest

from app.core.csrf import CSRF_COOKIE, CSRF_HEADER, new_csrf_token
from app.core.sessions import mint_session
from app.db import models


@pytest.fixture
async def session_user(db_session):
    org = models.Org(name="CsrfOrg", slug="csrf-org")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="csrf@example.com", name="C", google_sub="g-csrf")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)
    csrf = new_csrf_token()
    return {
        "cookie": {"voice_session": token, CSRF_COOKIE: csrf},
        "csrf": csrf,
    }


@pytest.mark.asyncio
async def test_get_does_not_require_csrf(client, session_user):
    r = await client.get("/v1/api-keys", cookies=session_user["cookie"])
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_session_write_without_csrf_header_is_403(client, session_user):
    r = await client.post("/v1/api-keys", json={"name": "x"}, cookies=session_user["cookie"])
    assert r.status_code == 403
    assert "csrf" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_session_write_with_mismatched_csrf_is_403(client, session_user):
    r = await client.post(
        "/v1/api-keys",
        json={"name": "x"},
        cookies=session_user["cookie"],
        headers={CSRF_HEADER: "not-the-cookie-value"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_session_write_with_matching_csrf_succeeds(client, session_user):
    r = await client.post(
        "/v1/api-keys",
        json={"name": "ok"},
        cookies=session_user["cookie"],
        headers={CSRF_HEADER: session_user["csrf"]},
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_bearer_writes_skip_csrf_entirely(client, auth_headers, db_session):
    # Build a writeable endpoint payload: POST /v1/agents only needs name.
    r = await client.post(
        "/v1/agents",
        json={"name": "no-csrf-needed-for-bearer"},
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text


@pytest.mark.asyncio
async def test_unauthed_write_passes_csrf_layer(client):
    # No session, no bearer → CSRF doesn't fire; the route's own auth dep does.
    r = await client.post("/v1/api-keys", json={"name": "x"})
    assert r.status_code == 401  # require_session rejects, not CSRF


@pytest.mark.asyncio
async def test_exempt_path_oauth_login_bypasses_csrf(client, monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_ID", "x")
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_SECRET", "y")
    from app.core import config

    config.get_settings.cache_clear()
    try:
        # /v1/auth/login/google is GET, but the exempt list also covers it.
        r = await client.get("/v1/auth/login/google", follow_redirects=False)
        assert r.status_code == 302
    finally:
        config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_session_cookie_mints_csrf_on_me(client, db_session):
    """First /me hit after upgrade sees no csrf cookie → server mints one."""
    org = models.Org(name="MeOrg", slug="me-csrf-org")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="me@example.com", name="M", google_sub="g-me")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)

    r = await client.get("/v1/auth/me", cookies={"voice_session": token})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("csrf_token"), str) and len(body["csrf_token"]) > 16
    assert "voice_csrf=" in r.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_logout_clears_both_cookies(client, session_user):
    r = await client.post("/v1/auth/logout", cookies=session_user["cookie"])
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "voice_session=" in set_cookie
    assert "voice_csrf=" in set_cookie
