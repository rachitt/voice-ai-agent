"""calendar adapter — JWT mint, token cache, event POST.

The HTTP layer is exercised against `httpx.MockTransport`; the JWT is
signed with a throwaway RSA keypair generated per-test so we never
depend on real Google credentials.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

from app.core.config import get_settings
from app.tools import calendar as cal_mod
from app.tools.builtins import REGISTRY, ToolContext


def _make_sa_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "svc@example.iam.gserviceaccount.com",
            "private_key": pem,
            "private_key_id": "kid-1",
        }
    )


@pytest.fixture(autouse=True)
def _wire_sa(monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", _make_sa_json())
    get_settings.cache_clear()
    cal_mod._reset_cache_for_tests()
    yield
    get_settings.cache_clear()
    cal_mod._reset_cache_for_tests()


def _patch_httpx(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_cls = httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(cal_mod.httpx, "AsyncClient", _Factory())


def test_load_sa_raises_when_unset(monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "")
    get_settings.cache_clear()
    with pytest.raises(cal_mod.CalendarConfigError):
        cal_mod._load_sa()


def test_load_sa_raises_on_malformed_json(monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "{not json")
    get_settings.cache_clear()
    with pytest.raises(cal_mod.CalendarConfigError):
        cal_mod._load_sa()


def test_load_sa_raises_when_field_missing(monkeypatch):
    monkeypatch.setenv(
        "VOICE_GOOGLE_SERVICE_ACCOUNT_JSON",
        json.dumps({"client_email": "x", "private_key": ""}),
    )
    get_settings.cache_clear()
    with pytest.raises(cal_mod.CalendarConfigError):
        cal_mod._load_sa()


def test_mint_jwt_has_required_claims():
    sa = cal_mod._load_sa()
    token = cal_mod._mint_jwt(sa, now=1_700_000_000)
    # Decode without verification to read claims (header carries the kid).
    claims = jose_jwt.get_unverified_claims(token)
    assert claims["iss"] == "svc@example.iam.gserviceaccount.com"
    assert claims["aud"] == cal_mod.TOKEN_URL
    assert claims["scope"] == cal_mod.SCOPE
    assert claims["exp"] - claims["iat"] == 3600
    header = jose_jwt.get_unverified_header(token)
    assert header["kid"] == "kid-1"
    assert header["alg"] == "RS256"


@pytest.mark.asyncio
async def test_get_access_token_caches_until_near_expiry(monkeypatch):
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(
                200, json={"access_token": "tok-abc", "expires_in": 3600}
            )
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)
    t1 = await cal_mod.get_access_token()
    t2 = await cal_mod.get_access_token()
    assert t1 == t2 == "tok-abc"
    assert len(calls) == 1  # cache hit on second call


@pytest.mark.asyncio
async def test_get_access_token_refreshes_when_near_expiry(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            # Expires in 30s → first call caches, next call must re-mint
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 30})
        return httpx.Response(404)

    _patch_httpx(monkeypatch, handler)
    await cal_mod.get_access_token()
    # Mutate cache so we can detect a real refresh.
    assert cal_mod._token_cache is not None
    cal_mod._token_cache.exp = time.time() + 10  # within the 60s skew band

    # Refresh should happen automatically.
    tok = await cal_mod.get_access_token()
    assert tok == "tok"


@pytest.mark.asyncio
async def test_book_event_happy_path(monkeypatch):
    posted: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        posted["url"] = str(req.url)
        posted["auth"] = req.headers.get("authorization")
        posted["body"] = json.loads(req.content)
        return httpx.Response(
            200,
            json={
                "id": "evt_1",
                "htmlLink": "https://cal/evt_1",
                "start": {"dateTime": "2026-05-15T15:00:00+00:00"},
                "end": {"dateTime": "2026-05-15T15:30:00+00:00"},
            },
        )

    _patch_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(
        title="Demo with Alice",
        start_iso="2026-05-15T15:00:00+00:00",
        attendee_email="alice@example.com",
    )
    assert out["event_id"] == "evt_1"
    assert posted["url"].endswith("/calendars/primary/events")
    assert posted["auth"] == "Bearer tok"
    assert posted["body"]["summary"] == "Demo with Alice"
    assert posted["body"]["attendees"] == [{"email": "alice@example.com"}]
    assert posted["body"]["start"]["dateTime"] == "2026-05-15T15:00:00+00:00"
    assert posted["body"]["end"]["dateTime"] == "2026-05-15T15:30:00+00:00"


@pytest.mark.asyncio
async def test_book_event_invalid_start_iso(monkeypatch):
    out = await cal_mod.book_event(title="x", start_iso="not-a-date")
    assert out["error"] == "invalid_start_iso"


@pytest.mark.asyncio
async def test_book_event_unconfigured_returns_typed_error(monkeypatch):
    monkeypatch.setenv("VOICE_GOOGLE_SERVICE_ACCOUNT_JSON", "")
    get_settings.cache_clear()
    cal_mod._reset_cache_for_tests()
    out = await cal_mod.book_event(title="x", start_iso="2026-05-15T15:00:00+00:00")
    assert out["error"] == "calendar_unconfigured"


@pytest.mark.asyncio
async def test_book_event_retries_once_on_401(monkeypatch):
    state = {"posts": 0, "tokens": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            state["tokens"] += 1
            return httpx.Response(
                200,
                json={"access_token": f"tok-{state['tokens']}", "expires_in": 3600},
            )
        state["posts"] += 1
        if state["posts"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        return httpx.Response(200, json={"id": "evt_after_retry"})

    _patch_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(
        title="X", start_iso="2026-05-15T15:00:00+00:00"
    )
    assert out["event_id"] == "evt_after_retry"
    assert state["posts"] == 2
    assert state["tokens"] == 2  # initial + forced refresh


@pytest.mark.asyncio
async def test_book_event_non_200_returns_error(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(403, json={"error": "forbidden"})

    _patch_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(title="X", start_iso="2026-05-15T15:00:00+00:00")
    assert out["error"] == "calendar_api"
    assert out["status"] == 403


@pytest.mark.asyncio
async def test_book_event_timeout(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        raise httpx.TimeoutException("slow")

    _patch_httpx(monkeypatch, handler)
    out = await cal_mod.book_event(title="X", start_iso="2026-05-15T15:00:00+00:00")
    assert out == {"error": "timeout"}


# ----- book_meeting builtin -------------------------------------------------


@pytest.mark.asyncio
async def test_book_meeting_builtin_validates_args():
    entry = REGISTRY["book_meeting"]
    ctx = ToolContext(call=None, db=None, args={"start_iso": "2026-05-15T15:00:00Z"})  # type: ignore[arg-type]
    out = await entry["handler"](ctx)
    assert out == {"error": "missing_title"}

    ctx = ToolContext(call=None, db=None, args={"title": "x"})  # type: ignore[arg-type]
    out = await entry["handler"](ctx)
    assert out == {"error": "missing_start_iso"}


@pytest.mark.asyncio
async def test_book_meeting_builtin_dispatches_to_calendar(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == cal_mod.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "evt_42",
                "htmlLink": "https://cal/evt_42",
                "start": {"dateTime": "2026-05-15T15:00:00+00:00"},
                "end": {"dateTime": "2026-05-15T15:30:00+00:00"},
            },
        )

    _patch_httpx(monkeypatch, handler)
    entry = REGISTRY["book_meeting"]
    ctx = ToolContext(
        call=None,  # type: ignore[arg-type]
        db=None,  # type: ignore[arg-type]
        args={
            "title": "Demo with Bob",
            "start_iso": "2026-05-15T15:00:00Z",
            "attendee_email": "bob@example.com",
        },
    )
    out = await entry["handler"](ctx)
    assert out["event_id"] == "evt_42"


def test_book_meeting_in_registry():
    entry = REGISTRY["book_meeting"]
    fn = entry["definition"]["function"]
    assert fn["name"] == "book_meeting"
    props = fn["parameters"]["properties"]
    assert {"title", "start_iso", "attendee_email", "duration_min"}.issubset(props)
