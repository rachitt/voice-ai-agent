from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Principal, require_api_key
from app.core.logging import log
from app.db.models import KbSource, KnowledgeBase
from app.db.session import get_db
from app.kb.loaders import UnsupportedSourceError, detect_kind, extract_text
from app.kb.store import ingest_source_text
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


@router.post(
    "/{kb_id}/sources/upload",
    response_model=KbSourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_source(
    kb_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_api_key),
) -> KbSource:
    """Upload a file (txt/md/pdf/docx), extract text, chunk+embed inline.

    Sync v1: blocks until embedding completes. A worker queue is the next step
    once docs grow past a few MB.
    """
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id
            )
        )
    ).scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge base not found")

    name = file.filename or "upload"
    try:
        kind = detect_kind(name)
    except UnsupportedSourceError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")

    try:
        text = extract_text(data, kind=kind)
    except Exception as exc:
        log.exception("kb.extract.err", err=str(exc))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"extract failed: {exc}") from exc

    src = KbSource(kb_id=kb_id, name=name, kind=kind, status="ingesting")
    db.add(src)
    await db.commit()
    await db.refresh(src)

    try:
        await ingest_source_text(
            db,
            kb_id=kb_id,
            source=src,
            raw_text=text,
            embedding_model=kb.embedding_model,
        )
    except Exception as exc:
        src.status = "error"
        src.error = str(exc)[:500]
        await db.commit()
        await db.refresh(src)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"embedding failed: {exc}") from exc

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
