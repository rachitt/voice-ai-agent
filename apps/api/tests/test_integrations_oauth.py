"""Per-org Google Calendar OAuth flow + adapter integration."""

from __future__ import annotations

import httpx
import pytest

from app.core import config as cfg
from app.core.sessions import mint_session
from app.db import models
from app.routers import integrations as integ_router
from app.tools import calendar as cal_mod


@pytest.fixture(autouse=True)
def _wire_google_oauth(monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_ID", "client-x")
    monkeypatch.setenv("VOICE_GOOGLE_OAUTH_CLIENT_SECRET", "secret-x")
    monkeypatch.setenv(
        "VOICE_GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:8000/v1/auth/callback/google",
    )
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _patch_httpx(monkeypatch, mod, handler):
    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(mod.httpx, "AsyncClient", _Factory())


# ----- /connect -------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_requires_session(client):
    r = await client.get("/v1/integrations/google/calendar/connect", follow_redirects=False)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_connect_302_to_google_with_calendar_scope(client, db_session):
    org = models.Org(name="O", slug="o-int")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="x@example.com", name="X", google_sub="g-int")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)

    r = await client.get(
        "/v1/integrations/google/calendar/connect",
        cookies={"voice_session": token},
        follow_redirects=False,
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "scope=openid+email" in loc or "scope=openid%20email" in loc
    assert "calendar.events" in loc
    assert "access_type=offline" in loc
    assert "prompt=consent" in loc  # forces refresh_token
    # State cookie carries org id alongside csrf token.
    assert "voice_int_state" in r.headers.get("set-cookie", "")


# ----- /callback ------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_persists_refresh_token(client, db_session, monkeypatch):
    org = models.Org(name="O", slug="o-cb")
    db_session.add(org)
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "access_token": "acc-1",
                    "refresh_token": "ref-1",
                    "expires_in": 3600,
                    "scope": "openid email https://www.googleapis.com/auth/calendar.events",
                },
            )
        if "userinfo" in str(req.url):
            return httpx.Response(200, json={"email": "cal@example.com"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, integ_router, handler)

    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=goodcode&state=st1",
        cookies={"voice_int_state": f"st1|{org.id}"},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    assert "/settings/integrations?connected=google_calendar" in r.headers["location"]

    row = (
        await db_session.execute(
            models.OAuthIntegration.__table__.select().where(
                models.OAuthIntegration.org_id == org.id
            )
        )
    ).first()
    assert row is not None
    assert row.refresh_token == "ref-1"
    assert row.account_email == "cal@example.com"


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(client):
    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=c&state=different",
        cookies={"voice_int_state": "expected|org_x"},
        follow_redirects=False,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_user_denied_redirects_with_error(client):
    r = await client.get(
        "/v1/integrations/google/calendar/callback?error=access_denied",
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "error=access_denied" in r.headers["location"]


@pytest.mark.asyncio
async def test_callback_missing_refresh_token_502(client, monkeypatch, db_session):
    org = models.Org(name="O", slug="o-cb-norefresh")
    db_session.add(org)
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(req.url):
            # Google sometimes omits refresh_token if user already granted before
            # without prompt=consent. We force consent → this is the misconfig path.
            return httpx.Response(200, json={"access_token": "acc", "expires_in": 3600})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, integ_router, handler)
    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=c&state=st",
        cookies={"voice_int_state": f"st|{org.id}"},
        follow_redirects=False,
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_callback_missing_code_400(client):
    r = await client.get(
        "/v1/integrations/google/calendar/callback?state=x",
        cookies={"voice_int_state": "x|org_y"},
        follow_redirects=False,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_malformed_state_cookie_400(client):
    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=c&state=s",
        cookies={"voice_int_state": "no-pipe-in-here"},
        follow_redirects=False,
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_callback_token_exchange_failure_502(client, monkeypatch, db_session):
    org = models.Org(name="O", slug="o-tok-fail")
    db_session.add(org)
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad client")

    _patch_httpx(monkeypatch, integ_router, handler)
    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=c&state=st",
        cookies={"voice_int_state": f"st|{org.id}"},
        follow_redirects=False,
    )
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_callback_upsert_overwrites_prior_integration(client, monkeypatch, db_session):
    org = models.Org(name="O", slug="o-upsert")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="OLD",
            account_email="stale@example.com",
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        if "token" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "access_token": "new-acc",
                    "refresh_token": "NEW",
                    "expires_in": 3600,
                    "scope": "calendar.events",
                },
            )
        if "userinfo" in str(req.url):
            return httpx.Response(200, json={"email": "fresh@example.com"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, integ_router, handler)
    r = await client.get(
        "/v1/integrations/google/calendar/callback?code=c&state=st",
        cookies={"voice_int_state": f"st|{org.id}"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    # Refresh+email overwritten in place — count remains 1.
    rows = (
        await db_session.execute(
            models.OAuthIntegration.__table__.select().where(
                models.OAuthIntegration.org_id == org.id
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].refresh_token == "NEW"
    assert rows[0].account_email == "fresh@example.com"


# ----- /status + /disconnect ------------------------------------------------


@pytest.mark.asyncio
async def test_status_returns_connected_when_row_present(client, db_session):
    org = models.Org(name="O", slug="o-stat")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="y@example.com", name="Y", google_sub="g-y")
    db_session.add(user)
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            account_email="me@example.com",
            refresh_token="ref-z",
            scopes={"granted": ["calendar.events"]},
        )
    )
    await db_session.commit()
    token = mint_session(user.id, org.id)
    r = await client.get(
        "/v1/integrations/google/calendar/status", cookies={"voice_session": token}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is True
    assert body["account_email"] == "me@example.com"


@pytest.mark.asyncio
async def test_status_returns_disconnected_when_no_row(client, db_session):
    org = models.Org(name="O", slug="o-empty")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="z@example.com", name="Z", google_sub="g-z3")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)
    r = await client.get(
        "/v1/integrations/google/calendar/status", cookies={"voice_session": token}
    )
    assert r.json() == {"connected": False}


@pytest.mark.asyncio
async def test_disconnect_revokes_and_deletes(client, db_session, monkeypatch):
    org = models.Org(name="O", slug="o-dc")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="d@example.com", name="D", google_sub="g-d")
    db_session.add(user)
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref-dc",
            scopes={"granted": []},
        )
    )
    await db_session.commit()
    token = mint_session(user.id, org.id)
    csrf = "csrf-" + token[-6:]

    revoke_hits: dict = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        revoke_hits["n"] += 1
        return httpx.Response(200, json={})

    _patch_httpx(monkeypatch, integ_router, handler)

    r = await client.delete(
        "/v1/integrations/google/calendar",
        cookies={"voice_session": token, "voice_csrf": csrf},
        headers={"x-csrf-token": csrf},
    )
    assert r.status_code == 204
    assert revoke_hits["n"] == 1

    # Row gone.
    r = await client.get(
        "/v1/integrations/google/calendar/status", cookies={"voice_session": token}
    )
    assert r.json() == {"connected": False}


@pytest.mark.asyncio
async def test_disconnect_when_no_integration_returns_204(client, db_session):
    org = models.Org(name="O", slug="o-no-disc")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="n@example.com", name="N", google_sub="g-n")
    db_session.add(user)
    await db_session.commit()
    token = mint_session(user.id, org.id)
    csrf = "csrf-" + token[-6:]
    r = await client.delete(
        "/v1/integrations/google/calendar",
        cookies={"voice_session": token, "voice_csrf": csrf},
        headers={"x-csrf-token": csrf},
    )
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_disconnect_swallows_revoke_failure(client, db_session, monkeypatch):
    """Google revoke endpoint down → local row still deleted."""
    org = models.Org(name="O", slug="o-revoke-err")
    db_session.add(org)
    await db_session.flush()
    user = models.User(org_id=org.id, email="r@example.com", name="R", google_sub="g-r2")
    db_session.add(user)
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref-r",
            scopes={"granted": []},
        )
    )
    await db_session.commit()
    token = mint_session(user.id, org.id)
    csrf = "csrf-" + token[-6:]

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("revoke endpoint down")

    _patch_httpx(monkeypatch, integ_router, handler)

    r = await client.delete(
        "/v1/integrations/google/calendar",
        cookies={"voice_session": token, "voice_csrf": csrf},
        headers={"x-csrf-token": csrf},
    )
    assert r.status_code == 204
    # Row is gone despite revoke crashing.
    r = await client.get(
        "/v1/integrations/google/calendar/status", cookies={"voice_session": token}
    )
    assert r.json() == {"connected": False}


# ----- adapter book_event_for_org ------------------------------------------


@pytest.mark.asyncio
async def test_book_event_for_org_uses_oauth_integration(db_session, monkeypatch):
    org = models.Org(name="O", slug="o-be")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            account_email="cal@example.com",
            refresh_token="ref-be",
            access_token="acc-still-good",
            expires_at=__import__("datetime").datetime.now(__import__("datetime").UTC)
            + __import__("datetime").timedelta(seconds=3600),
            scopes={"granted": ["calendar.events"]},
        )
    )
    await db_session.commit()

    posted: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if "calendar/v3/calendars/primary/events" in str(req.url):
            posted["auth"] = req.headers.get("authorization")
            posted["body"] = req.read()
            return httpx.Response(
                200,
                json={
                    "id": "evt_oauth",
                    "htmlLink": "https://cal/evt_oauth",
                    "start": {"dateTime": "2026-05-15T17:00:00+00:00"},
                    "end": {"dateTime": "2026-05-15T17:30:00+00:00"},
                },
            )
        return httpx.Response(404)

    _patch_httpx(monkeypatch, cal_mod, handler)

    out = await cal_mod.book_event_for_org(
        db=db_session,
        org_id=org.id,
        title="Demo with Carol",
        start_iso="2026-05-15T17:00:00+00:00",
        attendee_email="carol@example.com",
    )
    assert out["event_id"] == "evt_oauth"
    assert out["account_email"] == "cal@example.com"
    assert posted["auth"] == "Bearer acc-still-good"


@pytest.mark.asyncio
async def test_book_event_for_org_refreshes_expired_token(db_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-refresh")
    db_session.add(org)
    await db_session.flush()
    row = models.OAuthIntegration(
        org_id=org.id,
        provider="google_calendar",
        refresh_token="ref-refresh",
        access_token="acc-old",
        expires_at=datetime.now(UTC) - timedelta(seconds=10),  # expired
        scopes={"granted": []},
    )
    db_session.add(row)
    await db_session.commit()

    posts: dict = {"token_calls": 0, "event_calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(req.url):
            posts["token_calls"] += 1
            return httpx.Response(200, json={"access_token": "acc-fresh", "expires_in": 3600})
        if "/events" in str(req.url):
            posts["event_calls"] += 1
            assert req.headers.get("authorization") == "Bearer acc-fresh"
            return httpx.Response(200, json={"id": "evt_refreshed", "htmlLink": "https://x"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, cal_mod, handler)

    out = await cal_mod.book_event_for_org(
        db=db_session,
        org_id=org.id,
        title="x",
        start_iso="2026-05-15T17:00:00+00:00",
    )
    assert out["event_id"] == "evt_refreshed"
    assert posts["token_calls"] == 1
    assert posts["event_calls"] == 1


@pytest.mark.asyncio
async def test_book_event_for_org_refresh_failure_returns_typed_error(db_session, monkeypatch):
    """Refresh endpoint returns 401 → adapter surfaces calendar_token_refresh_failed."""
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-refresh-fail")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref-invalid",
            access_token="acc-x",
            expires_at=datetime.now(UTC) - timedelta(seconds=60),
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(req.url):
            return httpx.Response(401, json={"error": "invalid_grant"})
        return httpx.Response(500)

    _patch_httpx(monkeypatch, cal_mod, handler)

    # Ensure SA fallback is also unconfigured so we can assert a typed error.
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "")
    cfg.get_settings.cache_clear()
    cal_mod._reset_cache_for_tests()

    out = await cal_mod.book_event_for_org(
        db=db_session,
        org_id=org.id,
        title="x",
        start_iso="2026-05-15T17:00:00+00:00",
    )
    assert out.get("error") in {"calendar_unconfigured", "calendar_token_refresh_failed"}


@pytest.mark.asyncio
async def test_book_event_for_org_retries_on_401(db_session, monkeypatch):
    """Live POST returns 401 → adapter refreshes + retries once."""
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-401-retry")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref",
            access_token="acc-good",
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    state = {"events": 0, "tokens": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if "oauth2.googleapis.com/token" in str(req.url):
            state["tokens"] += 1
            return httpx.Response(200, json={"access_token": "acc-new", "expires_in": 3600})
        if "/events" in str(req.url):
            state["events"] += 1
            if state["events"] == 1:
                return httpx.Response(401, json={"error": "expired"})
            return httpx.Response(200, json={"id": "evt_after_retry"})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, cal_mod, handler)
    out = await cal_mod.book_event_for_org(
        db=db_session,
        org_id=org.id,
        title="x",
        start_iso="2026-05-15T17:00:00+00:00",
    )
    assert out["event_id"] == "evt_after_retry"
    assert state["events"] == 2
    assert state["tokens"] == 1  # one refresh on 401


@pytest.mark.asyncio
async def test_book_event_for_org_invalid_start_iso(db_session):
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-iso-bad")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref",
            access_token="acc",
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            scopes={"granted": []},
        )
    )
    await db_session.commit()
    out = await cal_mod.book_event_for_org(
        db=db_session, org_id=org.id, title="x", start_iso="not-an-iso"
    )
    assert out["error"] == "invalid_start_iso"


@pytest.mark.asyncio
async def test_book_event_for_org_timeout(db_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-tmo")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref",
            access_token="acc",
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    _patch_httpx(monkeypatch, cal_mod, handler)
    out = await cal_mod.book_event_for_org(
        db=db_session, org_id=org.id, title="x", start_iso="2026-05-15T17:00:00+00:00"
    )
    assert out == {"error": "timeout"}


@pytest.mark.asyncio
async def test_book_event_for_org_non_json_body(db_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-html")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref",
            access_token="acc",
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<html>oops</html>")

    _patch_httpx(monkeypatch, cal_mod, handler)
    out = await cal_mod.book_event_for_org(
        db=db_session, org_id=org.id, title="x", start_iso="2026-05-15T17:00:00+00:00"
    )
    assert out["error"] == "calendar_api"
    assert "raw" in out["body"]


@pytest.mark.asyncio
async def test_book_event_for_org_transport_error(db_session, monkeypatch):
    from datetime import UTC, datetime, timedelta

    org = models.Org(name="O", slug="o-trans")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        models.OAuthIntegration(
            org_id=org.id,
            provider="google_calendar",
            refresh_token="ref",
            access_token="acc",
            expires_at=datetime.now(UTC) + timedelta(seconds=3600),
            scopes={"granted": []},
        )
    )
    await db_session.commit()

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    _patch_httpx(monkeypatch, cal_mod, handler)
    out = await cal_mod.book_event_for_org(
        db=db_session, org_id=org.id, title="x", start_iso="2026-05-15T17:00:00+00:00"
    )
    assert out["error"] == "transport_error"


@pytest.mark.asyncio
async def test_book_event_for_org_falls_back_to_sa_when_no_integration(db_session, monkeypatch):
    """No integration row → adapter falls back to env-SA path. Without SA
    creds configured either, returns calendar_unconfigured."""
    org = models.Org(name="O", slug="o-no-int")
    db_session.add(org)
    await db_session.commit()
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "")
    cfg.get_settings.cache_clear()

    out = await cal_mod.book_event_for_org(
        db=db_session,
        org_id=org.id,
        title="x",
        start_iso="2026-05-15T17:00:00+00:00",
    )
    assert out["error"] == "calendar_unconfigured"
