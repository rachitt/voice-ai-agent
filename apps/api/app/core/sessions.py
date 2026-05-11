"""Cookie-session JWTs for OAuth-issued user sessions.

Separate from API-key bearer auth. JWT payload:
    {"sub": user_id, "org": org_id, "exp": unix_ts}
Signed with session_secret (HS256). Stored in an HttpOnly, SameSite=Lax cookie.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def _secret() -> str:
    # Re-use webhook_hmac_secret as the session key — single secret to rotate.
    return get_settings().webhook_hmac_secret


def mint_session(user_id: str, org_id: str, ttl_seconds: int | None = None) -> str:
    s = get_settings()
    ttl = ttl_seconds or s.session_ttl_seconds
    payload = {
        "sub": user_id,
        "org": org_id,
        "exp": int((datetime.now(UTC) + timedelta(seconds=ttl)).timestamp()),
        "iat": int(datetime.now(UTC).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def verify_session(token: str) -> dict[str, str] | None:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    sub = claims.get("sub")
    org = claims.get("org")
    if not isinstance(sub, str) or not isinstance(org, str):
        return None
    return {"sub": sub, "org": org}
