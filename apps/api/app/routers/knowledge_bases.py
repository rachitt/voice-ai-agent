import time

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthedPrincipal, require_principal
from app.core.config import get_settings
from app.core.logging import log
from app.db.models import KbSource, KnowledgeBase
from app.db.session import get_db
from app.kb.loaders import UnsupportedSourceError, detect_kind, extract_text
from app.kb.store import ingest_source_text, search
from app.schemas.knowledge_bases import (
    KbCreate,
    KbOut,
    KbQuery,
    KbQueryHit,
    KbQueryResult,
    KbSourceCreate,
    KbSourceOut,
)
from app.storage.s3 import put_object_bytes
from app.workers.kb_ingest import enqueue_kb_ingest

router = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KbOut, status_code=status.HTTP_201_CREATED)
async def create_kb(
    body: KbCreate,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> KnowledgeBase:
    kb = KnowledgeBase(org_id=p.org.id, **body.model_dump())
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get("", response_model=list[KbOut])
async def list_kbs(
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> list[KnowledgeBase]:
    rows = (
        (
            await db.execute(
                select(KnowledgeBase)
                .where(KnowledgeBase.org_id == p.org.id)
                .order_by(KnowledgeBase.name)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@router.post("/{kb_id}/sources", response_model=KbSourceOut, status_code=status.HTTP_201_CREATED)
async def add_source(
    kb_id: str,
    body: KbSourceCreate,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> KbSource:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id)
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
    p: AuthedPrincipal = Depends(require_principal),
) -> KbSource:
    """Upload a file (txt/md/pdf/docx), extract text, chunk+embed inline.

    Sync v1: blocks until embedding completes. A worker queue is the next step
    once docs grow past a few MB.
    """
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id)
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

    settings = get_settings()
    use_async = settings.enable_async_kb_ingest and settings.enable_object_store

    src = KbSource(kb_id=kb_id, name=name, kind=kind, status="queued" if use_async else "ingesting")
    db.add(src)
    await db.commit()
    await db.refresh(src)

    s3_key = await put_object_bytes(
        bucket=settings.s3_bucket_kb,
        key=f"kb/{kb_id}/{src.id}/{name}",
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )
    if s3_key:
        src.s3_key = s3_key
        await db.commit()
        await db.refresh(src)

    if use_async:
        if not s3_key:
            src.status = "error"
            src.error = "object store upload failed; cannot async-ingest"
            await db.commit()
            await db.refresh(src)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                "object store upload failed; cannot async-ingest",
            )
        await enqueue_kb_ingest(src.id)
        return src

    try:
        text = extract_text(data, kind=kind)
    except Exception as exc:
        log.exception("kb.extract.err", err=str(exc))
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"extract failed: {exc}") from exc

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


@router.post("/{kb_id}/query", response_model=KbQueryResult)
async def query_kb(
    kb_id: str,
    body: KbQuery,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> KbQueryResult:
    """Embed `query`, return top_k chunks with cosine scores.

    Useful for debugging KB retrieval from the dashboard before connecting
    the agent. Tenant-scoped — refuses to search KBs from other orgs.
    """
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id)
        )
    ).scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge base not found")
    k = max(1, min(int(body.top_k or 5), 20))
    if not body.query.strip():
        return KbQueryResult(hits=[], elapsed_ms=0)
    started = time.perf_counter()
    hits = await search(db, kb_id=kb_id, query=body.query, embedding_model=kb.embedding_model, k=k)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if not hits:
        return KbQueryResult(hits=[], elapsed_ms=elapsed_ms)
    src_rows = (
        await db.execute(
            select(KbSource.id, KbSource.name).where(KbSource.id.in_({h.source_id for h in hits}))
        )
    ).all()
    names = {sid: name for sid, name in src_rows}
    return KbQueryResult(
        hits=[
            KbQueryHit(
                chunk_id=h.chunk_id,
                source_id=h.source_id,
                source_name=names.get(h.source_id),
                text=h.text,
                score=h.score,
            )
            for h in hits
        ],
        elapsed_ms=elapsed_ms,
    )


@router.get("/{kb_id}/sources", response_model=list[KbSourceOut])
async def list_sources(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> list[KbSource]:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.org_id == p.org.id)
        )
    ).scalar_one_or_none()
    if not kb:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "knowledge base not found")
    rows = (
        (
            await db.execute(
                select(KbSource).where(KbSource.kb_id == kb_id).order_by(KbSource.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
