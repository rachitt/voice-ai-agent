from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.db.models import KbSource, KnowledgeBase
from app.db.session import get_db
from app.schemas.knowledge_bases import KbCreate, KbOut, KbSourceCreate, KbSourceOut

router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KbOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    body: KbCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> KnowledgeBase:
    kb = KnowledgeBase(org_id=p.org.id, **body.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("", response_model=list[KbOut])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> list[KnowledgeBase]:
    rows = (
        await db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.org_id == p.org.id)
            .order_by(KnowledgeBase.name)
        )
    ).scalars().all()
    return list(rows)


@router.post("/{kb_id}/sources", response_model=KbSourceOut, status_code=status.HTTP_201_CREATED)
async def add_source(
    kb_id: str,
    body: KbSourceCreate,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> KbSource:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id
            )
        )
    ).scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge base not found")
    src = KbSource(kb_id=kb_id, **body.model_dump())
    db.add(src)
    await db.commit()
    await db.refresh(src)
    return src


@router.get("/{kb_id}/sources", response_model=list[KbSourceOut])
async def list_sources(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> list[KbSource]:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id
            )
        )
    ).scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge base not found")
    rows = (
        await db.execute(
            select(KbSource).where(KbSource.kb_id == kb_id).order_by(KbSource.created_at.desc())
        )
    ).scalars().all()
    return list(rows)
