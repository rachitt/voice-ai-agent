"""Google OAuth 2.0 authorization-code flow + session cookie.

Flow:
  GET /v1/auth/login/google      → 302 to Google consent screen (with state).
  GET /v1/auth/callback/google   → exchanges code, upserts User+Org, mints
                                    session cookie, 302 to web_app_base_url.
  GET /v1/auth/me                → current user info from session cookie.
  POST /v1/auth/logout           → clears cookie.

Coexists with API-key bearer auth. Web frontend uses the session cookie;
SDKs use API keys via /v1/api-keys/...

State + nonce live in short-lived signed cookies so we stay stateless.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import (  # noqa: F401
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.logging import log
from app.core.security import hash_api_key
from app.core.sessions import mint_session, verify_session
from app.db.models import ApiKey, Org, User
from app.db.session import get_db

router = APIRouter(prefix="/v1/auth", tags=["auth"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_COOKIE = "voice_oauth_state"


def _secure_cookie() -> bool:
    """Secure flag on every non-dev env. Dev keeps it off so localhost (no TLS) works."""
    return get_settings().env != "dev"


def _slugify(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    return out.strip("-")[:60] or "user"


def _require_oauth_config() -> dict[str, str]:
    s = get_settings()
    if not s.google_oauth_client_id or not s.google_oauth_client_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "google oauth not configured (set VOICE_GOOGLE_OAUTH_CLIENT_ID + _SECRET)",
        )
    return {
        "client_id": s.google_oauth_client_id,
        "client_secret": s.google_oauth_client_secret,
        "redirect_uri": s.google_oauth_redirect_uri,
    }


@router.get("/login/google")
async def login_google() -> RedirectResponse:
    cfg = _require_oauth_config()
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    resp = RedirectResponse(url=f"{GOOGLE_AUTH}?{urlencode(params)}", status_code=302)
    resp.set_cookie(
        STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
    )
    return resp


@router.get("/callback/google")
async def callback_google(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
    oauth_state_cookie: str | None = Cookie(default=None, alias=STATE_COOKIE),
) -> RedirectResponse:
    cfg = _require_oauth_config()
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing code")
    if not state or not oauth_state_cookie or not secrets.compare_digest(state, oauth_state_cookie):
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
                "oauth.token.err", status=token_resp.status_code, body=token_resp.text[:200]
            )
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "token exchange failed")
        access_token = token_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "missing access_token")

        user_resp = await http.get(
            GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access_token}"}
        )
        if user_resp.status_code != 200:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "userinfo failed")
        info: dict[str, Any] = user_resp.json()

    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "userinfo missing sub/email")

    user = await _upsert_user(db, info=info)
    request.state.user_id = user.id

    cookie_value = mint_session(user.id, user.org_id)
    s = get_settings()
    resp = RedirectResponse(url=s.web_app_base_url, status_code=302)
    resp.set_cookie(
        s.session_cookie_name,
        cookie_value,
        max_age=s.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        path="/",
    )
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@router.get("/me")
async def me(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    s = get_settings()
    raw = request.cookies.get(s.session_cookie_name)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no session")
    claims = verify_session(raw)
    if not claims:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid session")
    user = await db.get(User, claims["sub"])
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user gone")
    org = await db.get(Org, user.org_id)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
        },
        "org": {"id": org.id, "name": org.name, "slug": org.slug} if org else None,
    }


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    s = get_settings()
    response.delete_cookie(
        s.session_cookie_name,
        path="/",
        secure=_secure_cookie(),
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


class ApiKeyExchangeIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=128)


@router.post("/session/api-key")
async def exchange_api_key_for_session(
    body: ApiKeyExchangeIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Exchange a long-lived API key for an httpOnly session cookie.

    Lets the dashboard avoid storing the API key in localStorage (XSS risk)
    while still bootstrapping without a full Google OAuth setup. The minted
    cookie is identical to the OAuth-issued one — same TTL, same flags —
    so middleware / `require_session` doesn't need to know the difference.

    A synthetic "service" user is auto-provisioned per org if none exists,
    so the session JWT always points at a real `User` row.
    """
    raw = body.api_key.strip()
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty api key")

    row = (
        await db.execute(
            select(ApiKey, Org)
            .join(Org, Org.id == ApiKey.org_id)
            .where(ApiKey.key_hash == hash_api_key(raw), ApiKey.revoked_at.is_(None))
        )
    ).first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    api_key, org = row

    # Prefer the org's first real user (OAuth-provisioned). Fall back to a
    # synthetic one so API-key-bootstrap envs without Google OAuth still work.
    user = (
        await db.execute(
            select(User).where(User.org_id == org.id).order_by(User.created_at.asc()).limit(1)
        )
    ).scalar_one_or_none()
    if not user:
        user = User(
            org_id=org.id,
            email=f"service@{org.slug or 'org'}.local",
            name="API Service",
            google_sub=None,
        )
        db.add(user)
        await db.flush()

    api_key.last_used_at = datetime.now(UTC)
    user.last_login_at = datetime.now(UTC)
    await db.commit()

    s = get_settings()
    cookie_value = mint_session(user.id, org.id)
    response.set_cookie(
        s.session_cookie_name,
        cookie_value,
        max_age=s.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=_secure_cookie(),
        path="/",
    )
    return {
        "user": {"id": user.id, "email": user.email, "name": user.name},
        "org": {"id": org.id, "name": org.name, "slug": org.slug},
    }


async def _upsert_user(db: AsyncSession, *, info: dict[str, Any]) -> User:
    sub = str(info["sub"])
    email = str(info["email"])
    name = info.get("name")
    picture = info.get("picture")

    # 1. Match by google_sub
    user = (await db.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
    if user:
        user.last_login_at = datetime.now(UTC)
        if name and not user.name:
            user.name = name
        if picture:
            user.avatar_url = picture
        await db.commit()
        await db.refresh(user)
        return user

    # 2. Match by email — bind google_sub on first OAuth login
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user:
        user.google_sub = sub
        user.last_login_at = datetime.now(UTC)
        if name and not user.name:
            user.name = name
        if picture:
            user.avatar_url = picture
        await db.commit()
        await db.refresh(user)
        return user

    # 3. Provision new Org + User
    base_slug = _slugify(email.split("@", 1)[0])
    org_slug = base_slug
    for _ in range(20):
        exists = (await db.execute(select(Org).where(Org.slug == org_slug))).scalar_one_or_none()
        if not exists:
            break
        org_slug = f"{base_slug}-{secrets.token_hex(2)}"
    else:
        org_slug = f"{base_slug}-{secrets.token_hex(4)}"

    org = Org(name=(name or email.split("@", 1)[0]), slug=org_slug)
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=email,
        name=name,
        avatar_url=picture,
        google_sub=sub,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("oauth.user.provisioned", user_id=user.id, org_id=org.id)
    return user
