"""arq task: ingest a KbSource asynchronously.

The HTTP upload endpoint persists raw bytes to MinIO then enqueues this task.
The worker re-fetches bytes, extracts text, chunks, embeds, and writes chunks.
Status transitions: queued → ingesting → ready | error.

Run the worker:
    uv run arq app.workers.kb_ingest.WorkerSettings
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import KbSource, KnowledgeBase
from app.db.session import SessionLocal
from app.kb.loaders import extract_text
from app.kb.store import ingest_source_text
from app.storage.s3 import get_object_bytes


async def ingest_kb_source(ctx: dict[str, Any], source_id: str) -> dict[str, Any]:
    """Idempotent: re-running a 'ready' source is a no-op (returns existing chunk count)."""
    settings = get_settings()
    async with SessionLocal() as db:
        src = await db.get(KbSource, source_id)
        if src is None:
            return {"ok": False, "error": "source_not_found", "source_id": source_id}
        if src.status == "ready":
            return {"ok": True, "already_ready": True, "source_id": source_id}
        if not src.s3_key:
            src.status = "error"
            src.error = "no s3_key set; cannot async-ingest"
            await db.commit()
            return {"ok": False, "error": "missing_s3_key", "source_id": source_id}

        kb = await db.get(KnowledgeBase, src.kb_id)
        if kb is None:
            src.status = "error"
            src.error = "kb deleted before ingest"
            await db.commit()
            return {"ok": False, "error": "kb_not_found", "source_id": source_id}

        src.status = "ingesting"
        src.error = None
        await db.commit()

        try:
            raw = await get_object_bytes(bucket=settings.s3_bucket_kb, key=src.s3_key)
            text = extract_text(raw, kind=src.kind)
            n = await ingest_source_text(
                db,
                kb_id=src.kb_id,
                source=src,
                raw_text=text,
                embedding_model=kb.embedding_model,
            )
            return {"ok": True, "chunks": n, "source_id": source_id}
        except Exception as exc:
            log.exception("worker.kb_ingest.err", source=source_id, err=str(exc))
            src.status = "error"
            src.error = str(exc)[:500]
            await db.commit()
            return {"ok": False, "error": str(exc), "source_id": source_id}


async def enqueue_kb_ingest(source_id: str) -> str | None:
    """Push a job onto the queue. Returns the arq job id or None if disabled."""
    settings = get_settings()
    if not settings.enable_async_kb_ingest:
        return None
    from arq.connections import RedisSettings, create_pool

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job("ingest_kb_source", source_id)
        return job.job_id if job else None
    finally:
        await pool.aclose()


class WorkerSettings:  # arq picks this up via `arq app.workers.kb_ingest.WorkerSettings`
    functions = [ingest_kb_source]
    keep_result = 600
    max_jobs = 4

    @staticmethod
    def redis_settings():  # type: ignore[override]
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(get_settings().redis_url)
