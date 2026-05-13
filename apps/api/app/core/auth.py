from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_api_key
from app.core.sessions import verify_session
from app.db.models import ApiKey, Org, User
from app.db.session import get_db


@dataclass
class Principal:
    """Bearer-API-key principal. Used by external SDK callers."""

    org: Org
    api_key: ApiKey
    user: None = None
    method: Literal["api_key"] = "api_key"


@dataclass
class SessionPrincipal:
    """Cookie-session principal. Used by dashboard browser users."""

    user: User
    org: Org
    api_key: None = None
    method: Literal["session"] = "session"


@dataclass
class AuthedPrincipal:
    """Either-or principal — used by routes that accept both auth methods.

    The dashboard speaks via the session cookie; external integrations speak
    via long-lived API keys. Read-only fields:
        .org       — always present
        .user      — present for session auth, None for API-key auth
        .api_key   — present for API-key auth, None for session auth
        .method    — \"session\" or \"api_key\" — for audit logging
    """

    org: Org
    user: User | None
    api_key: ApiKey | None
    method: Literal["session", "api_key"]


async def require_api_key(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "empty bearer token")

    key_hash = hash_api_key(raw)
    row = (
        await db.execute(
            select(ApiKey, Org)
            .join(Org, Org.id == ApiKey.org_id)
            .where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
        )
    ).first()
    if not row:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")

    api_key, org = row
    await db.execute(
        update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=datetime.now(UTC))
    )
    await db.commit()
    return Principal(org=org, api_key=api_key)


async def require_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SessionPrincipal:
    """Resolve session cookie → (User, Org). Used by dashboard routes that
    must not accept long-lived API keys for self-management."""
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
    if not org:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "org gone")
    return SessionPrincipal(user=user, org=org)


async def require_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthedPrincipal:
    """Accept EITHER a session cookie OR a Bearer API key.

    Preferred for any route that the dashboard browser needs to call as well
    as external SDK consumers. Routes that must reject API-key auth
    (e.g. minting/revoking API keys) keep using `require_session` instead.

    Cookie auth wins when both are present — browser sessions are scoped to a
    real user, which is the stricter identity.
    """
    s = get_settings()
    raw_cookie = request.cookies.get(s.session_cookie_name)
    if raw_cookie:
        claims = verify_session(raw_cookie)
        if claims:
            user = await db.get(User, claims["sub"])
            if user:
                org = await db.get(Org, user.org_id)
                if org:
                    return AuthedPrincipal(
                        org=org, user=user, api_key=None, method="session"
                    )

    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
        if raw:
            key_hash = hash_api_key(raw)
            row = (
                await db.execute(
                    select(ApiKey, Org)
                    .join(Org, Org.id == ApiKey.org_id)
                    .where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
                )
            ).first()
            if row:
                api_key, org = row
                await db.execute(
                    update(ApiKey)
                    .where(ApiKey.id == api_key.id)
                    .values(last_used_at=datetime.now(UTC))
                )
                await db.commit()
                return AuthedPrincipal(
                    org=org, user=None, api_key=api_key, method="api_key"
                )

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
