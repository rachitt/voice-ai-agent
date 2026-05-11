import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.core.config import get_settings
from app.core.security import hash_api_key
from app.db.models import Agent, ApiKey, Call, CallDirection, CallStatus, Org
from app.db.session import get_db
from app.pipeline import event_bus
from app.pipeline.web_session import (
    SSE_TOKEN_TTL_SECONDS,
    mint_sse_token,
    mint_ws_token,
    verify_sse_token,
)
from app.schemas.calls import (
    CallDetailOut,
    CallListItem,
    CallListPage,
    CallOut,
    PhoneCallCreate,
    StreamTokenOut,
    WebCallCreate,
    WebCallCreated,
)
from app.telephony.telnyx import TelnyxClient

router = APIRouter(prefix="/v1/calls", tags=["calls"])


async def _agent_or_404(db: AsyncSession, org_id: str, agent_id: str) -> Agent:
    ag = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    ).scalar_one_or_none()
    if not ag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return ag


def _telnyx_client_factory() -> TelnyxClient:
    """Indirection so tests can patch this with a fake."""
    return TelnyxClient()


@router.post("/phone", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_phone_call(
    body: PhoneCallCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Call:
    settings = get_settings()
    if not settings.telnyx_api_key or not settings.telnyx_connection_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "telnyx not configured (set VOICE_TELNYX_API_KEY and VOICE_TELNYX_CONNECTION_ID)",
        )
    ag = await _agent_or_404(db, p.org.id, body.agent_id)
    call = Call(
        org_id=p.org.id,
        agent_id=ag.id,
        agent_version_id=ag.published_version_id,
        direction=CallDirection.outbound,
        status=CallStatus.queued,
        from_number=body.from_number,
        to_number=body.to_number,
        dynamic_variables=body.dynamic_variables,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)

    token = mint_ws_token(call.id)
    stream_url = f"{settings.public_ws_base_url}/v1/telephony/telnyx/media?call_id={call.id}&token={token}"
    webhook_url = f"{settings.public_base_url}/v1/webhooks/telnyx"

    telnyx = _telnyx_client_factory()
    try:
        resp = await telnyx.initiate_call(
            to=body.to_number,
            from_=body.from_number,
            webhook_url=webhook_url,
            stream_url=stream_url,
        )
        provider_id = (resp.get("data") or {}).get("call_control_id") or (resp.get("data") or {}).get("id")
        if provider_id:
            call.provider_call_id = provider_id
        call.status = CallStatus.ringing
        await db.commit()
        await db.refresh(call)
    except Exception as exc:
        call.status = CallStatus.failed
        await db.commit()
        await db.refresh(call)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"telnyx initiate_call failed: {exc}"
        ) from exc
    finally:
        await telnyx.aclose()

    return call


@router.post("/web", response_model=WebCallCreated, status_code=status.HTTP_201_CREATED)
async def create_web_call(
    body: WebCallCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> WebCallCreated:
    ag = await _agent_or_404(db, p.org.id, body.agent_id)
    call = Call(
        org_id=p.org.id,
        agent_id=ag.id,
        agent_version_id=ag.published_version_id,
        direction=CallDirection.web,
        status=CallStatus.queued,
        dynamic_variables=body.dynamic_variables,
    )
    db.add(call)
    await db.commit()
    await db.refresh(call)
    token = mint_ws_token(call.id)
    return WebCallCreated.model_validate(
        {
            **CallOut.model_validate(call, from_attributes=True).model_dump(),
            "ws_token": token,
            "ws_url": f"/v1/calls/{call.id}/ws?token={token}",
        }
    )


@router.get("", response_model=CallListPage)
async def list_calls(
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
    agent_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    direction: str | None = Query(default=None),
    has_recording: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(
        default=None,
        description="Opaque cursor; pass the previous response's next_cursor.",
    ),
) -> CallListPage:
    """List calls in the caller's org, newest first. Cursor is the last seen
    `created_at` ISO timestamp + id, keyset-paginated so it stays consistent
    under concurrent inserts."""
    stmt = select(Call).where(Call.org_id == p.org.id)
    if agent_id:
        stmt = stmt.where(Call.agent_id == agent_id)
    if status_filter:
        stmt = stmt.where(Call.status == status_filter)
    if direction:
        stmt = stmt.where(Call.direction == direction)
    if has_recording is True:
        stmt = stmt.where(Call.recording_s3_key.isnot(None))
    elif has_recording is False:
        stmt = stmt.where(Call.recording_s3_key.is_(None))

    if cursor:
        try:
            import base64
            from datetime import datetime as _dt
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = base64.urlsafe_b64decode(padded.encode()).decode()
            ts_str, last_id = decoded.split("|", 1)
            ts = _dt.fromisoformat(ts_str)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid cursor") from exc
        stmt = stmt.where(
            (Call.created_at < ts)
            | ((Call.created_at == ts) & (Call.id < last_id))
        )

    stmt = stmt.order_by(Call.created_at.desc(), Call.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).scalars().all()
    has_more = len(rows) > limit
    page_rows = list(rows[:limit])

    items = [
        CallListItem.model_validate(
            {
                **CallListItem.model_validate(r, from_attributes=True).model_dump(),
                "has_recording": bool(r.recording_s3_key),
            }
        )
        for r in page_rows
    ]
    next_cursor: str | None = None
    if has_more and page_rows:
        import base64
        last = page_rows[-1]
        raw = f"{last.created_at.isoformat()}|{last.id}"
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    return CallListPage(items=items, next_cursor=next_cursor)


@router.get("/{call_id}", response_model=CallDetailOut)
async def get_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Call:
    call = (
        await db.execute(select(Call).where(Call.id == call_id, Call.org_id == p.org.id))
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return call


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> "StreamingResponse":
    """Stream the call's WAV recording bytes from object storage."""
    call = (
        await db.execute(select(Call).where(Call.id == call_id, Call.org_id == p.org.id))
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    if not call.recording_s3_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no recording for this call")
    from app.storage.s3 import get_object_bytes  # local import: storage is optional

    try:
        data = await get_object_bytes(
            bucket=get_settings().s3_bucket_recordings, key=call.recording_s3_key
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"recording fetch failed: {exc}") from exc

    async def _iter():
        yield data

    return StreamingResponse(
        _iter(),
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{call.id}.wav"'},
    )


async def _principal_via_bearer(
    authorization: str | None,
    db: AsyncSession,
) -> Principal | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        return None
    row = (
        await db.execute(
            select(ApiKey, Org)
            .join(Org, Org.id == ApiKey.org_id)
            .where(ApiKey.key_hash == hash_api_key(raw), ApiKey.revoked_at.is_(None))
        )
    ).first()
    if not row:
        return None
    api_key, org = row
    return Principal(org=org, api_key=api_key)


@router.post("/{call_id}/stream-token", response_model=StreamTokenOut)
async def mint_stream_token(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> StreamTokenOut:
    """Mint a short-lived (5 min) token bound to this call+org for the SSE stream.

    Avoids exposing the long-lived API key in EventSource URLs.
    """
    call = (
        await db.execute(select(Call).where(Call.id == call_id, Call.org_id == p.org.id))
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    token, exp = mint_sse_token(call.id, p.org.id)
    return StreamTokenOut(token=token, expires_at=exp, ttl_seconds=SSE_TOKEN_TTL_SECONDS)


@router.get("/{call_id}/stream")
async def stream_call_events(
    call_id: str,
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Server-Sent Events stream of live transcript/tool/agent events.

    Spectator channel — does not see binary audio. Closes when the WS
    producer terminates the call. EventSource lacks header auth so we
    accept a short-lived signed `?token=` minted via /stream-token.
    Programmatic clients can still pass an API key via Authorization.
    """
    org_id: str | None = None
    if authorization:
        principal = await _principal_via_bearer(authorization, db)
        if principal:
            org_id = principal.org.id
    if org_id is None and token:
        org_id = verify_sse_token(token, call_id=call_id)
        if org_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired stream token")
    if org_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing credentials")

    call = (
        await db.execute(select(Call).where(Call.id == call_id, Call.org_id == org_id))
    ).scalar_one_or_none()
    if not call:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")

    async def gen() -> AsyncIterator[bytes]:
        # initial hello so the client knows the stream is alive
        yield b"event: ready\ndata: {}\n\n"
        async for ev in event_bus.subscribe(call_id):
            yield f"data: {json.dumps(ev)}\n\n".encode()

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Content-Type": "text/event-stream",
    }
    return StreamingResponse(gen(), headers=headers, media_type="text/event-stream")
