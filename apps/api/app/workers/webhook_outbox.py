"""arq worker for the webhook delivery outbox.

The outbox table is the durable queue: any code path that produces a
customer-facing webhook (call.completed, analysis.completed, etc.)
inserts a row via `app.webhooks.dispatcher.enqueue`. This worker
periodically drains pending rows, signs + POSTs the body, and applies
exponential backoff on failure.

Modes:
  • cron tick: `arq` runs `tick_webhook_outbox` every few seconds via
    `cron_jobs`, which calls `dispatcher.run_once()`.
  • direct enqueue: `enqueue_webhook_delivery(outbox_id)` for fan-out
    paths that want immediate delivery without waiting for the cron tick.

Run the worker:
    uv run arq app.workers.webhook_outbox.WorkerSettings
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import log
from app.db.models import WebhookOutbox
from app.db.session import SessionLocal
from app.webhooks import dispatcher


async def tick_webhook_outbox(ctx: dict[str, Any]) -> dict[str, Any]:
    """Cron-driven sweep over pending rows. Returns count processed."""
    try:
        processed = await dispatcher.run_once()
    except Exception as exc:
        log.exception("worker.webhook_outbox.tick.err", err=str(exc))
        return {"ok": False, "processed": 0, "error": str(exc)}
    return {"ok": True, "processed": processed}


async def deliver_webhook(ctx: dict[str, Any], outbox_id: str) -> dict[str, Any]:
    """Direct delivery of a single outbox row. Used by fan-out producers
    that want low-latency dispatch on top of the cron sweep."""
    async with SessionLocal() as db:
        row = await db.get(WebhookOutbox, outbox_id)
        if row is None:
            return {"ok": False, "error": "outbox_not_found", "id": outbox_id}
        if row.status != "pending":
            return {"ok": True, "already_done": True, "id": outbox_id, "status": row.status}

        async with httpx.AsyncClient() as client:
            ok = await dispatcher.deliver_one(client, row)

        row.attempts += 1
        if ok:
            row.status = "delivered"
            row.delivered_at = datetime.now(UTC)
        elif row.attempts >= dispatcher.MAX_ATTEMPTS:
            row.status = "dead"
        else:
            row.next_attempt_at = dispatcher._next_attempt(row.attempts)
        await db.commit()
        return {"ok": ok, "id": outbox_id, "status": row.status}


async def enqueue_webhook_delivery(outbox_id: str) -> str | None:
    """Push a direct-delivery job. Returns arq job id or None if disabled."""
    settings = get_settings()
    if not settings.enable_webhook_worker:
        return None
    from arq.connections import RedisSettings, create_pool

    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job("deliver_webhook", outbox_id)
        return job.job_id if job else None
    finally:
        await pool.aclose()


async def pending_count() -> int:
    """Count pending+due rows. Used by health/metrics + tests."""
    now = datetime.now(UTC)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(WebhookOutbox.id).where(
                    WebhookOutbox.status == "pending",
                    WebhookOutbox.next_attempt_at <= now,
                )
            )
        ).scalars().all()
        return len(rows)


def _cron_jobs():
    """Build the arq cron schedule lazily so import-time has no arq dep."""
    from arq import cron

    return [
        cron(tick_webhook_outbox, second={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]


class WorkerSettings:  # arq picks this up via `arq app.workers.webhook_outbox.WorkerSettings`
    functions = [deliver_webhook, tick_webhook_outbox]
    keep_result = 600
    max_jobs = 8
    cron_jobs = _cron_jobs()

    @staticmethod
    def redis_settings():  # type: ignore[override]
        from arq.connections import RedisSettings

        return RedisSettings.from_dsn(get_settings().redis_url)
