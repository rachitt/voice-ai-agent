from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import prefixed_id
from app.core.logging import log
from app.core.security import sign_webhook
from app.db.models import WebhookOutbox
from app.db.session import SessionLocal

MAX_ATTEMPTS = 3
BACKOFF_BASE_S = 5.0


def _next_attempt(attempts: int) -> datetime:
    delay = BACKOFF_BASE_S * (2**attempts)
    return datetime.now(UTC) + timedelta(seconds=delay)


async def enqueue(
    db: AsyncSession, *, org_id: str, url: str, event: str, payload: dict
) -> WebhookOutbox:
    row = WebhookOutbox(
        id=prefixed_id("whx"),
        org_id=org_id,
        url=url,
        event=event,
        payload=payload,
        next_attempt_at=datetime.now(UTC),
        status="pending",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def deliver_one(client: httpx.AsyncClient, row: WebhookOutbox) -> bool:
    body = json.dumps({"event": row.event, "data": row.payload}, separators=(",", ":")).encode()
    headers = {
        "content-type": "application/json",
        "x-voice-signature": sign_webhook(body),
        "x-voice-event": row.event,
        "x-voice-delivery": row.id,
    }
    try:
        r = await client.post(row.url, content=body, headers=headers, timeout=10.0)
        ok = 200 <= r.status_code < 300
        if not ok:
            log.info("webhook.deliver.fail", url=row.url, status=r.status_code)
        return ok
    except Exception as exc:
        log.info("webhook.deliver.error", url=row.url, err=str(exc))
        return False


async def run_once() -> int:
    """Pull pending rows, attempt delivery, update state. Returns processed count."""
    now = datetime.now(UTC)
    processed = 0
    async with SessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(WebhookOutbox)
                    .where(
                        WebhookOutbox.status == "pending",
                        WebhookOutbox.next_attempt_at <= now,
                    )
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )

        if not rows:
            return 0

        async with httpx.AsyncClient() as client:
            for row in rows:
                ok = await deliver_one(client, row)
                row.attempts += 1
                processed += 1
                if ok:
                    row.status = "delivered"
                    row.delivered_at = datetime.now(UTC)
                elif row.attempts >= MAX_ATTEMPTS:
                    row.status = "dead"
                else:
                    row.next_attempt_at = _next_attempt(row.attempts)
        await db.commit()
    return processed


async def run_forever(poll_s: float = 2.0) -> None:
    log.info("webhook.dispatcher.start")
    while True:
        try:
            await run_once()
        except Exception as exc:
            log.exception("webhook.dispatcher.tick.error", err=str(exc))
        await asyncio.sleep(poll_s)
