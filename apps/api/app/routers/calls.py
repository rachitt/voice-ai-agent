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
from app.pipeline.web_session import mint_ws_token
from app.schemas.calls import CallOut, PhoneCallCreate, WebCallCreate, WebCallCreated
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


@router.get("/{call_id}", response_model=CallOut)
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


async def _principal_via_header_or_query(
    authorization: str | None,
    token: str | None,
    db: AsyncSession,
) -> Principal:
    """SSE-friendly auth: accept Bearer header OR ?token= query string."""
    raw: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1].strip()
    if not raw and token:
        raw = token.strip()
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing api key")
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
    return Principal(org=org, api_key=api_key)


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
    also accept the api key via `?token=`.
    """
    p = await _principal_via_header_or_query(authorization, token, db)
    call = (
        await db.execute(select(Call).where(Call.id == call_id, Call.org_id == p.org.id))
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
