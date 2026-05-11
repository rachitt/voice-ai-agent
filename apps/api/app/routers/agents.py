from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import Principal, require_api_key
from app.db.models import Agent, AgentVersion
from app.db.session import get_db
from app.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentOut,
    AgentUpdate,
    AgentVersionOut,
    PublishIn,
)

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Agent:
    agent = Agent(org_id=p.org.id, name=body.name)
    db.add(agent)
    await db.flush()

    version = AgentVersion(
        agent_id=agent.id,
        version=1,
        **body.model_dump(exclude={"name"}),
    )
    db.add(version)
    await db.commit()
    await db.refresh(agent, attribute_names=["versions"])
    return agent


@router.get("", response_model=list[AgentOut])
async def list_agents(
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> list[Agent]:
    rows = (
        await db.execute(
            select(Agent).where(Agent.org_id == p.org.id).order_by(Agent.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Agent:
    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.org_id == p.org.id)
            .options(selectinload(Agent.versions))
        )
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentVersionOut)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> AgentVersion:
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.org_id == p.org.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    if body.name is not None:
        agent.name = body.name

    next_version = (
        await db.execute(
            select(func.coalesce(func.max(AgentVersion.version), 0) + 1).where(
                AgentVersion.agent_id == agent_id
            )
        )
    ).scalar_one()

    new_version = AgentVersion(
        agent_id=agent_id,
        version=next_version,
        **body.model_dump(exclude={"name"}, exclude_none=True),
    )
    db.add(new_version)
    await db.commit()
    await db.refresh(new_version)
    return new_version


@router.post("/{agent_id}/publish", response_model=AgentDetail)
async def publish_agent(
    agent_id: str,
    body: PublishIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> Agent:
    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.org_id == p.org.id)
            .options(selectinload(Agent.versions))
        )
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")

    ver = (
        await db.execute(
            select(AgentVersion).where(
                AgentVersion.id == body.version_id, AgentVersion.agent_id == agent_id
            )
        )
    ).scalar_one_or_none()
    if not ver:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "version not found")

    await db.execute(update(AgentVersion).where(AgentVersion.id == ver.id).values(env=body.env))
    agent.published_version_id = ver.id
    await db.commit()
    await db.refresh(agent, attribute_names=["versions"])
    return agent
