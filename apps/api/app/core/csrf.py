"""Double-submit-cookie CSRF protection for cookie-session callers.

SameSite=Lax already blocks cross-site CSRF for non-GET methods, but it
does NOT defend against same-site attackers (a sibling subdomain, a
compromised first-party iframe, an injected form on the same origin).
The double-submit cookie pattern closes that gap:

  1. On session mint, we also set a non-httpOnly `voice_csrf` cookie
     containing a high-entropy random token.
  2. The web client reads the cookie via `document.cookie` and copies it
     into an `X-CSRF-Token` header on state-changing requests.
  3. The middleware compares header against cookie via constant-time
     compare. Forged requests from another origin can read the cookie
     value (with XSS) but not set the header on a victim's browser.

Bearer-API-key callers are exempt — they're not browsers and don't have
the same vulnerability shape.

The middleware is intentionally simple:
  * GET/HEAD/OPTIONS — always skipped
  * No session cookie present — skipped (no session to forge against)
  * Authorization: Bearer present — skipped (API-key auth)
  * Path on the exempt list (login/exchange/webhooks) — skipped
"""

from __future__ import annotations

import secrets

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings

CSRF_COOKIE = "voice_csrf"
CSRF_HEADER = "x-csrf-token"

# Endpoints that legitimately accept POST/PUT without a CSRF token:
#   * login / oauth callback — runs before a session even exists
#   * api-key exchange       — the API key itself is the proof-of-identity
#   * webhooks               — signed by the provider, no browser involvement
#   * logout                 — idempotent + non-authenticated outcome
CSRF_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/v1/auth/login/",
    "/v1/auth/callback/",
    "/v1/auth/session/api-key",
    "/v1/auth/logout",
    # OAuth callbacks come from Google with no CSRF token; state cookie
    # serves the equivalent role for this path.
    "/v1/integrations/google/calendar/callback",
    "/v1/webhooks/",
    "/v1/telephony/",
    "/healthz",
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def new_csrf_token() -> str:
    """High-entropy token suitable for double-submit. 32 bytes → 43 chars."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, *, secure: bool) -> None:
    """Attach the CSRF cookie. Must NOT be httpOnly — JS reads it for the header."""
    s = get_settings()
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=s.session_ttl_seconds,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in CSRF_EXEMPT_PREFIXES)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforce double-submit-cookie CSRF on state-changing session calls."""

    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS:
            return await call_next(request)
        if _is_exempt(request.url.path):
            return await call_next(request)

        s = get_settings()
        session_cookie = request.cookies.get(s.session_cookie_name)
        auth_header = request.headers.get("authorization", "")

        # Only session-cookie callers need CSRF protection. Pure Bearer-API-key
        # callers (external SDKs) skip the check; if a session cookie exists
        # we enforce double-submit even when a Bearer header is also present
        # because the cookie path remains exploitable.
        if not session_cookie:
            _ = auth_header  # kept for clarity; pure-Bearer requests skip CSRF
            return await call_next(request)

        cookie_token = request.cookies.get(CSRF_COOKIE)
        header_token = request.headers.get(CSRF_HEADER)
        if not cookie_token or not header_token:
            return JSONResponse(
                {"detail": "csrf token missing"}, status_code=403
            )
        if not secrets.compare_digest(cookie_token, header_token):
            return JSONResponse(
                {"detail": "csrf token mismatch"}, status_code=403
            )
        return await call_next(request)
