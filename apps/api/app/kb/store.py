"""KB ingestion + retrieval. Postgres + pgvector."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import KbChunk, KbSource, KnowledgeBase
from app.kb.chunker import chunk_text
from app.pipeline.llm import embed


@dataclass
class Retrieval:
    chunk_id: str
    source_id: str
    text: str
    score: float


async def ingest_source_text(
    db: AsyncSession,
    *,
    kb_id: str,
    source: KbSource,
    raw_text: str,
    embedding_model: str,
) -> int:
    chunks = chunk_text(raw_text)
    if not chunks:
        source.status = "empty"
        await db.commit()
        return 0

    embeddings = await embed(model_id=embedding_model, texts=[c.text for c in chunks])
    for c, vec in zip(chunks, embeddings, strict=True):
        db.add(
            KbChunk(
                kb_id=kb_id,
                source_id=source.id,
                chunk_index=c.index,
                text=c.text,
                embedding=vec,
            )
        )
    source.status = "ready"
    await db.commit()
    log.info("kb.ingest.done", source=source.id, chunks=len(chunks))
    return len(chunks)


async def search(
    db: AsyncSession, *, kb_id: str, query: str, embedding_model: str, k: int = 5
) -> list[Retrieval]:
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    ).scalar_one_or_none()
    if not kb:
        return []
    model = embedding_model or kb.embedding_model
    qvec = (await embed(model_id=model, texts=[query]))[0]

    rows = (
        await db.execute(
            select(
                KbChunk.id,
                KbChunk.source_id,
                KbChunk.text,
                KbChunk.embedding.cosine_distance(qvec).label("dist"),
            )
            .where(KbChunk.kb_id == kb_id)
            .order_by("dist")
            .limit(k)
        )
    ).all()

    return [
        Retrieval(chunk_id=r[0], source_id=r[1], text=r[2], score=float(1.0 - r[3])) for r in rows
    ]
