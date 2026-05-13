"""Google Calendar adapter — mint service-account access token, create events.

Tiny scope on purpose:
  * sign a service-account JWT (RS256)
  * exchange it for an OAuth2 access token (cached until ~60s before expiry)
  * POST to /calendar/v3/calendars/{calId}/events

We deliberately avoid `google-auth` / `google-api-python-client` to keep
the binary footprint small and the call-path mockable with `httpx.MockTransport`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from jose import jwt  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.core.logging import log

TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_BASE = "https://www.googleapis.com/calendar/v3"
SCOPE = "https://www.googleapis.com/auth/calendar"


@dataclass
class _CachedToken:
    access_token: str
    exp: float  # epoch seconds


_token_cache: _CachedToken | None = None


class CalendarConfigError(RuntimeError):
    """Raised when service-account JSON is missing or malformed."""


def _load_sa() -> dict[str, Any]:
    raw = get_settings().google_service_account_json
    if not raw:
        raise CalendarConfigError("google_service_account_json not configured")
    try:
        sa = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CalendarConfigError(f"invalid service-account JSON: {exc}") from exc
    for k in ("client_email", "private_key", "private_key_id"):
        if not sa.get(k):
            raise CalendarConfigError(f"service-account missing {k}")
    return sa


def _mint_jwt(sa: dict[str, Any], *, now: float | None = None) -> str:
    iat = int(now if now is not None else time.time())
    payload = {
        "iss": sa["client_email"],
        "scope": SCOPE,
        "aud": TOKEN_URL,
        "iat": iat,
        "exp": iat + 3600,
    }
    return jwt.encode(
        payload,
        sa["private_key"],
        algorithm="RS256",
        headers={"kid": sa["private_key_id"]},
    )


async def _exchange_for_access_token(assertion: str) -> tuple[str, int]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    if r.status_code != 200:
        raise CalendarConfigError(f"token exchange failed: {r.status_code} {r.text[:300]}")
    body = r.json()
    return body["access_token"], int(body.get("expires_in", 3600))


async def get_access_token(*, force_refresh: bool = False) -> str:
    """Returns a cached access token, refreshing 60s before expiry."""
    global _token_cache
    now = time.time()
    if (
        not force_refresh
        and _token_cache is not None
        and _token_cache.exp - now > 60
    ):
        return _token_cache.access_token
    sa = _load_sa()
    assertion = _mint_jwt(sa, now=now)
    access_token, expires_in = await _exchange_for_access_token(assertion)
    _token_cache = _CachedToken(access_token=access_token, exp=now + expires_in)
    return access_token


def _reset_cache_for_tests() -> None:
    """Test-only: drop the cached token so the next call re-mints."""
    global _token_cache
    _token_cache = None


async def book_event(
    *,
    title: str,
    start_iso: str,
    attendee_email: str | None = None,
    duration_min: int | None = None,
    calendar_id: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Create a Calendar event. Returns Google's event payload on success."""
    settings = get_settings()
    cal = calendar_id or settings.google_calendar_id
    duration = duration_min or settings.google_calendar_default_duration_min
    try:
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    except ValueError as exc:
        return {"error": "invalid_start_iso", "detail": str(exc)}
    end = start + timedelta(minutes=duration)
    body: dict[str, Any] = {
        "summary": title,
        "description": description or "",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    if attendee_email:
        body["attendees"] = [{"email": attendee_email}]

    try:
        access_token = await get_access_token()
    except CalendarConfigError as exc:
        log.warning("calendar.config_error", err=str(exc))
        return {"error": "calendar_unconfigured", "detail": str(exc)}

    url = f"{CALENDAR_BASE}/calendars/{cal}/events"
    headers = {
        "authorization": f"Bearer {access_token}",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return {"error": "timeout"}
    except Exception as exc:
        log.exception("calendar.post.err", err=str(exc))
        return {"error": "transport_error", "detail": str(exc)}

    if r.status_code == 401:
        # Token may have been revoked / clock-skewed — force-refresh once.
        try:
            access_token = await get_access_token(force_refresh=True)
        except CalendarConfigError as exc:
            return {"error": "calendar_unconfigured", "detail": str(exc)}
        headers["authorization"] = f"Bearer {access_token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=body, headers=headers)

    try:
        payload = r.json()
    except Exception:
        payload = {"raw": r.text[:1000]}
    if not 200 <= r.status_code < 300:
        return {"error": "calendar_api", "status": r.status_code, "body": payload}
    return {
        "event_id": payload.get("id"),
        "html_link": payload.get("htmlLink"),
        "start": payload.get("start"),
        "end": payload.get("end"),
    }
