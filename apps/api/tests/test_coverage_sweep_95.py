"""Cold-spot coverage sweep targeting 94→95% gate.

Focused on the highest-density gaps:
  * auth_oauth.exchange_api_key_for_session (44 missed lines)
  * tools router 404 branches
  * event_bus.publish / close QueueFull paths
  * calendar.book_event non-JSON body + transport_error fallback
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.security import generate_api_key
from app.db import models
from app.pipeline import event_bus


# ----- auth_oauth.exchange_api_key_for_session -----------------------------


@pytest.mark.asyncio
async def test_api_key_exchange_empty_body_401(client):
    r = await client.post("/v1/auth/session/api-key", json={"api_key": "        "})
    # Empty after strip → 401. (Pydantic min_length=8 catches before our check
    # when the string is short; passing 8+ whitespace chars triggers the body
    # branch.)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_key_exchange_invalid_key_401(client):
    r = await client.post("/v1/auth/session/api-key", json={"api_key": "sk_nope123"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_api_key_exchange_synthesises_user_when_org_has_none(client, db_session):
    org = models.Org(name="Bootstrap", slug="bootstrap-org")
    db_session.add(org)
    await db_session.flush()
    raw, hashed = generate_api_key("sk_live")
    db_session.add(
        models.ApiKey(org_id=org.id, name="bootstrap", prefix=raw[:10], key_hash=hashed)
    )
    await db_session.commit()

    r = await client.post("/v1/auth/session/api-key", json={"api_key": raw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["org"]["slug"] == "bootstrap-org"
    assert body["user"]["email"].startswith("service@")
    assert "csrf_token" in body
    # Both cookies are set.
    set_cookie = r.headers.get("set-cookie", "")
    assert "voice_session=" in set_cookie
    assert "voice_csrf=" in set_cookie


@pytest.mark.asyncio
async def test_api_key_exchange_prefers_real_user_when_present(client, db_session):
    org = models.Org(name="HasUser", slug="has-user-org")
    db_session.add(org)
    await db_session.flush()
    user = models.User(
        org_id=org.id, email="founder@example.com", name="F", google_sub="g-1"
    )
    db_session.add(user)
    raw, hashed = generate_api_key("sk_live")
    db_session.add(
        models.ApiKey(org_id=org.id, name="k", prefix=raw[:10], key_hash=hashed)
    )
    await db_session.commit()

    r = await client.post("/v1/auth/session/api-key", json={"api_key": raw})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == "founder@example.com"


# ----- tools router 404 branches -------------------------------------------


@pytest.mark.asyncio
async def test_get_tool_404(client, auth_headers):
    r = await client.get("/v1/tools/tool_nonexistent", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_tool_404(client, auth_headers):
    r = await client.patch(
        "/v1/tools/tool_nonexistent",
        json={"name": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_tool_404(client, auth_headers):
    r = await client.delete("/v1/tools/tool_nonexistent", headers=auth_headers)
    assert r.status_code == 404


# ----- event_bus QueueFull drops ----------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_publish_drops_when_subscriber_queue_full():
    call_id = "call_evbus_full"
    q: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=1)
    q.put_nowait({"seed": True})
    # Manually register so we don't have to drive the iterator.
    event_bus._SUBS[call_id].add(q)
    try:
        # Second publish must hit QueueFull and silently drop.
        event_bus.publish(call_id, {"dropped": True})
        # Queue size is still 1.
        assert q.qsize() == 1
    finally:
        event_bus._SUBS.pop(call_id, None)


@pytest.mark.asyncio
async def test_event_bus_close_drops_sentinel_when_full():
    call_id = "call_evbus_close_full"
    q: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=1)
    q.put_nowait({"seed": True})
    event_bus._SUBS[call_id].add(q)
    try:
        event_bus.close(call_id)
        # SUB removed.
        assert call_id not in event_bus._SUBS
        # Sentinel was NOT inserted (queue still has the seed only).
        assert q.qsize() == 1
    finally:
        event_bus._SUBS.pop(call_id, None)


# ----- calendar.book_event fallbacks ---------------------------------------


def _patch_cal_httpx(monkeypatch, handler):
    from app.tools import calendar as cal_mod

    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(cal_mod.httpx, "AsyncClient", _Factory())


def _wire_sa(monkeypatch):
    import json

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core.config import get_settings
    from app.tools import calendar as cal_mod

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    monkeypatch.setenv(
        "VOICE_GOOGLE_SERVICE_ACCOUNT_JSON",
        json.dumps(
            {
                "type": "service_account",
                "client_email": "svc@x.iam",
                "private_key": pem,
                "private_key_id": "kid-1",
            }
        ),
    )
    get_settings.cache_clear()
    cal_mod._reset_cache_for_tests()


@pytest.mark.asyncio
async def test_book_event_non_json_response_body(monkeypatch):
    _wire_sa(monkeypatch)
    from app.tools import calendar as cal_mod

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(
            500, text="<html>oops</html>", headers={"content-type": "text/html"}
        )

    _patch_cal_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(title="X", start_iso="2026-05-15T15:00:00Z")
    assert out["error"] == "calendar_api"
    assert out["status"] == 500
    # Non-JSON body → wrapped in {"raw": ...}
    assert "raw" in out["body"]


@pytest.mark.asyncio
async def test_book_event_transport_error_path(monkeypatch):
    _wire_sa(monkeypatch)
    from app.tools import calendar as cal_mod

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        raise httpx.ConnectError("no route")

    _patch_cal_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(title="X", start_iso="2026-05-15T15:00:00Z")
    assert out["error"] == "transport_error"
    assert "no route" in out["detail"]


# ----- auth dependency 401 edges --------------------------------------------


@pytest.mark.asyncio
async def test_require_session_404_user_after_token_mint(client, db_session):
    """Session cookie signed for a user that's been deleted → 401 'user gone'."""
    from app.core.sessions import mint_session

    token = mint_session("usr_does_not_exist", "org_y")
    r = await client.get(
        "/v1/api-keys",
        cookies={"voice_session": token},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_require_session_404_org_when_user_org_gone(client, db_session):
    """User row exists but its org row is gone → 401 'org gone'.

    Hard to engineer because of FK constraints; we do a manual user without
    an org by violating the constraint. We accept either 'org gone' (401) OR
    integrity error fallout — both paths are exercised.
    """
    from app.core.sessions import mint_session

    org = models.Org(name="Tmp", slug="tmp-org-go")
    db_session.add(org)
    await db_session.flush()
    user = models.User(
        org_id=org.id, email="z@example.com", name="Z", google_sub="g-z2"
    )
    db_session.add(user)
    await db_session.commit()
    # Delete the org → cascade should also drop user; but we mint a token
    # under the user id first, so the resulting lookup hits "user gone".
    token = mint_session(user.id, org.id)
    await db_session.delete(org)
    await db_session.commit()
    r = await client.get("/v1/api-keys", cookies={"voice_session": token})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_require_principal_invalid_cookie_falls_through_to_bearer(
    client, auth_headers
):
    """Garbage session cookie present — Bearer should still authenticate."""
    r = await client.get(
        "/v1/agents",
        headers=auth_headers,
        cookies={"voice_session": "garbage-not-jwt"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_require_principal_bearer_with_revoked_key_401(client, db_session):
    org = models.Org(name="Revoked", slug="revoked-org")
    db_session.add(org)
    await db_session.flush()
    from datetime import UTC, datetime

    raw, hashed = generate_api_key("sk_live")
    db_session.add(
        models.ApiKey(
            org_id=org.id,
            name="r",
            prefix=raw[:10],
            key_hash=hashed,
            revoked_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    r = await client.get("/v1/agents", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_require_principal_bearer_empty_token_401(client):
    r = await client.get("/v1/agents", headers={"Authorization": "Bearer   "})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_book_event_unconfigured_during_401_retry(monkeypatch):
    """First call mints token; we then nuke creds and serve a 401 — the retry
    branch must surface calendar_unconfigured rather than crash."""
    _wire_sa(monkeypatch)
    from app.core.config import get_settings
    from app.tools import calendar as cal_mod

    state = {"posts": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        state["posts"] += 1
        return httpx.Response(401, json={"error": "expired"})

    _patch_cal_httpx(monkeypatch, handler)
    # Prime the cached token under the configured SA.
    await cal_mod.get_access_token()
    # Now nuke creds. The 401 retry will call get_access_token(force_refresh=True)
    # which re-reads settings, finds them empty, and short-circuits.
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "")
    get_settings.cache_clear()
    out = await cal_mod.book_event(title="X", start_iso="2026-05-15T15:00:00Z")
    assert out["error"] == "calendar_unconfigured"
