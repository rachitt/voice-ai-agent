from dataclasses import dataclass
from datetime import UTC, datetime

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
    org: Org
    api_key: ApiKey


@dataclass
class SessionPrincipal:
    user: User
    org: Org


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
