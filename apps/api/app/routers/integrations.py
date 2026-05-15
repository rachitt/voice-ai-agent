"""Per-org OAuth integrations (Google Calendar, etc.).

Separate from `/v1/auth/login/google` (which is for dashboard sign-in only).
This router lets an authenticated dashboard user click "Connect Calendar"
and grant the workspace API access to their calendar via OAuth 2.0
authorization-code flow. The resulting refresh_token lands in
`OAuthIntegration` keyed by `(org_id, provider)`.

Endpoints:
  GET    /v1/integrations/google/calendar/connect   → 302 to Google consent
  GET    /v1/integrations/google/calendar/callback  → exchange code, store, redirect
  GET    /v1/integrations/google/calendar/status    → connected/disconnected
  DELETE /v1/integrations/google/calendar           → revoke + delete row
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SessionPrincipal, require_session
from app.core.config import get_settings
from app.core.logging import log
from app.db.models import OAuthIntegration
from app.db.session import get_db

router = APIRouter(prefix="/v1/integrations", tags=["integrations"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
INTEGRATION_STATE_COOKIE = "voice_int_state"
PROVIDER = "google_calendar"


def _secure_cookie() -> bool:
    return get_settings().env != "dev"


def _require_oauth_config() -> dict[str, str]:
    s = get_settings()
    if not s.google_oauth_client_id or not s.google_oauth_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "google oauth not configured (set VOICE_GOOGLE_OAUTH_CLIENT_ID + _SECRET)",
        )
    # Reuse the dashboard sign-in redirect_uri base — we override the path
    # to the integration callback. Apps that need different redirects can
    # add a second client_id + override here.
    redirect = s.google_oauth_redirect_uri.replace(
        "/v1/auth/callback/google", "/v1/integrations/google/calendar/callback"
    )
    return {
        "client_id": s.google_oauth_client_id,
        "client_secret": s.google_oauth_client_secret,
        "redirect_uri": redirect,
    }


@router.get("/google/calendar/connect")
async def connect_google_calendar(
    p: SessionPrincipal = Depends(require_session),
) -> RedirectResponse:
    """Kick off OAuth — 302 to Google consent. Caller must be signed in."""
    cfg = _require_oauth_config()
    state = secrets.token_urlsafe(24)
    # Embed the org id in the state cookie alongside CSRF token so the
    # callback can resolve the integration target without trusting query
    # params. The cookie is httpOnly + SameSite=Lax + short-TTL.
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": f"openid email {CALENDAR_SCOPE}",
        "state": state,
        "access_type": "offline",  # needed to get refresh_token
        "prompt": "consent",  # force refresh_token on every connect
        "include_granted_scopes": "true",
    }
    resp = RedirectResponse(url=f"{GOOGLE_AUTH}?{urlencode(params)}", status_code=302)
    resp.set_cookie(
        INTEGRATION_STATE_COOKIE,
        f"{state}|{p.org.id}",
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        path="/",
    )
    return resp


@router.get("/google/calendar/callback")
async def callback_google_calendar(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    state_cookie: str | None = Cookie(default=None, alias=INTEGRATION_STATE_COOKIE),
) -> RedirectResponse:
    cfg = _require_oauth_config()
    s = get_settings()
    if error:
        # User clicked "deny" — bounce back to the app with the error in the URL.
        return RedirectResponse(
            url=f"{s.web_app_base_url}/settings/integrations?error={error}", status_code=302
        )
    if not code or not state or not state_cookie:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code or state")
    try:
        expected_state, org_id = state_cookie.split("|", 1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "malformed state cookie") from exc
    if not secrets.compare_digest(state, expected_state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid state")

    async with httpx.AsyncClient(timeout=10.0) as http:
        token_resp = await http.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": cfg["redirect_uri"],
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            log.warning(
                "integration.token.err",
                status=token_resp.status_code,
                body=token_resp.text[:200],
            )
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "token exchange failed")
        tok = token_resp.json()
        access_token = tok.get("access_token")
        refresh_token = tok.get("refresh_token")
        if not access_token or not refresh_token:
            # Without refresh_token, the connection can't survive an hour.
            # Force prompt=consent above prevents Google from omitting it.
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "missing tokens")
        expires_in = int(tok.get("expires_in", 3600))
        scopes = (tok.get("scope") or "").split()

        ui_resp = await http.get(
            GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"}
        )
        account_email = None
        if ui_resp.status_code == 200:
            account_email = ui_resp.json().get("email")

    # Upsert by (org_id, provider).
    existing = (
        await db.execute(
            select(OAuthIntegration).where(
                OAuthIntegration.org_id == org_id,
                OAuthIntegration.provider == PROVIDER,
            )
        )
    ).scalar_one_or_none()
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    if existing:
        existing.refresh_token = refresh_token
        existing.access_token = access_token
        existing.expires_at = expires_at
        existing.scopes = {"granted": scopes}
        if account_email:
            existing.account_email = account_email
    else:
        db.add(
            OAuthIntegration(
                org_id=org_id,
                provider=PROVIDER,
                account_email=account_email,
                refresh_token=refresh_token,
                access_token=access_token,
                expires_at=expires_at,
                scopes={"granted": scopes},
            )
        )
    await db.commit()

    resp = RedirectResponse(
        url=f"{s.web_app_base_url}/settings/integrations?connected=google_calendar",
        status_code=302,
    )
    resp.delete_cookie(INTEGRATION_STATE_COOKIE, path="/")
    return resp


@router.get("/google/calendar/status")
async def status_google_calendar(
    db: AsyncSession = Depends(get_db),
    p: SessionPrincipal = Depends(require_session),
) -> dict[str, Any]:
    row = (
        await db.execute(
            select(OAuthIntegration).where(
                OAuthIntegration.org_id == p.org.id,
                OAuthIntegration.provider == PROVIDER,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "account_email": row.account_email,
        "scopes": (row.scopes or {}).get("granted", []),
        "connected_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.delete("/google/calendar", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_google_calendar(
    db: AsyncSession = Depends(get_db),
    p: SessionPrincipal = Depends(require_session),
) -> Response:
    row = (
        await db.execute(
            select(OAuthIntegration).where(
                OAuthIntegration.org_id == p.org.id,
                OAuthIntegration.provider == PROVIDER,
            )
        )
    ).scalar_one_or_none()
    if not row:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Best-effort revoke at Google so the user sees it disappear in their
    # account dashboard too. Failure here doesn't block deletion locally.
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            await http.post(GOOGLE_REVOKE, data={"token": row.refresh_token})
    except Exception as exc:
        log.info("integration.revoke.err", err=str(exc))
    await db.delete(row)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
