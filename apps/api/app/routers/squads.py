from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import AuthedPrincipal, require_principal
from app.db.models import Agent, Squad, SquadEdge
from app.db.session import get_db
from app.schemas.squads import SquadCreate, SquadOut

router = APIRouter(prefix="/v1/squads", tags=["squads"])


async def _validate_agents(db: AsyncSession, org_id: str, agent_ids: set[str]) -> None:
    if not agent_ids:
        return
    rows = (
        (await db.execute(select(Agent.id).where(Agent.org_id == org_id, Agent.id.in_(agent_ids))))
        .scalars()
        .all()
    )
    missing = agent_ids - set(rows)
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"agents not found in org: {sorted(missing)}"
        )


@router.post("", response_model=SquadOut, status_code=status.HTTP_201_CREATED)
async def create_squad(
    body: SquadCreate,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> Squad:
    referenced = {body.root_agent_id}
    for e in body.edges:
        referenced.add(e.from_agent_id)
        referenced.add(e.to_agent_id)
    await _validate_agents(db, p.org.id, referenced)

    squad = Squad(org_id=p.org.id, name=body.name, root_agent_id=body.root_agent_id)
    db.add(squad)
    await db.flush()
    for e in body.edges:
        db.add(SquadEdge(squad_id=squad.id, **e.model_dump()))
    await db.commit()

    return (
        await db.execute(
            select(Squad).where(Squad.id == squad.id).options(selectinload(Squad.edges))
        )
    ).scalar_one()


@router.get("", response_model=list[SquadOut])
async def list_squads(
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> list[Squad]:
    rows = (
        (
            await db.execute(
                select(Squad)
                .where(Squad.org_id == p.org.id)
                .order_by(Squad.created_at.desc())
                .options(selectinload(Squad.edges))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/{squad_id}", response_model=SquadOut)
async def get_squad(
    squad_id: str,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> Squad:
    sq = (
        await db.execute(
            select(Squad)
            .where(Squad.id == squad_id, Squad.org_id == p.org.id)
            .options(selectinload(Squad.edges))
        )
    ).scalar_one_or_none()
    if not sq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "squad not found")
    return sq
