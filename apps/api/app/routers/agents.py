from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import Principal, require_api_key
from app.db.models import Agent, AgentEnv, AgentVersion
from app.db.session import get_db
from app.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentOut,
    AgentUpdate,
    AgentVersionOut,
    PublishIn,
)
from app.schemas.flow_graph_validators import validate_flow_graph

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


_VERSION_FIELDS = (
    "first_message",
    "system_prompt",
    "model_id",
    "voice_id",
    "stt_id",
    "language",
    "interruption_sensitivity",
    "vad_silence_ms",
    "flow_graph",
    "tools",
    "knowledge_base_ids",
    "analysis_plan",
    "server_url",
)


def _clone_version(src: AgentVersion, *, version: int, env: str) -> AgentVersion:
    return AgentVersion(
        agent_id=src.agent_id,
        version=version,
        env=env,
        first_message=src.first_message,
        system_prompt=src.system_prompt,
        model_id=src.model_id,
        voice_id=src.voice_id,
        stt_id=src.stt_id,
        language=src.language,
        interruption_sensitivity=src.interruption_sensitivity,
        vad_silence_ms=src.vad_silence_ms,
        flow_graph=src.flow_graph,
        tools=list(src.tools or []),
        knowledge_base_ids=list(src.knowledge_base_ids or []),
        analysis_plan=src.analysis_plan,
        server_url=src.server_url,
    )


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

    draft = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id, AgentVersion.env == AgentEnv.draft)
            .order_by(AgentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if draft is None:
        latest = (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == agent_id)
                .order_by(AgentVersion.version.desc())
                .limit(1)
            )
        ).scalar_one()
        draft = _clone_version(latest, version=latest.version + 1, env=AgentEnv.draft)
        db.add(draft)

    patch = body.model_dump(exclude={"name"}, exclude_unset=True)
    for k, v in patch.items():
        if k in _VERSION_FIELDS:
            setattr(draft, k, v)

    await db.commit()
    await db.refresh(draft)
    return draft


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

    if ver.flow_graph is not None:
        result = validate_flow_graph(ver.flow_graph)
        if not result.ok:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"errors": result.errors, "warnings": result.warnings},
            )

    await db.execute(update(AgentVersion).where(AgentVersion.id == ver.id).values(env=body.env))
    agent.published_version_id = ver.id

    next_version = (
        await db.execute(
            select(func.coalesce(func.max(AgentVersion.version), 0) + 1).where(
                AgentVersion.agent_id == agent_id
            )
        )
    ).scalar_one()
    new_draft = _clone_version(ver, version=next_version, env=AgentEnv.draft)
    db.add(new_draft)

    await db.commit()
    await db.refresh(agent, attribute_names=["versions"])
    return agent
