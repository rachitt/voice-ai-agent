from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.db.models import Agent, Call, CallDirection, CallStatus
from app.db.session import get_db
from app.schemas.calls import CallOut, PhoneCallCreate, WebCallCreate

router = APIRouter(prefix="/v1/calls", tags=["calls"])


async def _agent_or_404(db: AsyncSession, org_id: str, agent_id: str) -> Agent:
    ag = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id))
    ).scalar_one_or_none()
    if not ag:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return ag


@router.post("/phone", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_phone_call(
    body: PhoneCallCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Call:
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
    # TODO: enqueue telnyx outbound dial in pipeline worker
    return call


@router.post("/web", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def create_web_call(
    body: WebCallCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Call:
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
    return call


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
