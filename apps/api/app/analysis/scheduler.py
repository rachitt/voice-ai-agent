"""Fire-and-forget post-call analysis trigger.

WS handlers call `schedule_post_call(call_id)` after finalising a call. The
scheduler opens a fresh DB session, runs `analyze_call`, then enqueues an
`analysis.completed` webhook for any AgentVersion server_url configured.

Disabled by default — set `VOICE_ENABLE_POST_CALL_ANALYSIS=true` in prod.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.analysis.runner import analyze_call
from app.core.config import get_settings
from app.core.logging import log
from app.db.models import AgentVersion, Call
from app.db.session import SessionLocal
from app.webhooks import dispatcher as webhook_dispatcher


def schedule_post_call(call_id: str) -> asyncio.Task | None:
    """Schedule a background analysis run. Returns the task handle (mostly
    for tests) or None when analysis is disabled."""
    if not get_settings().enable_post_call_analysis:
        return None
    return asyncio.create_task(_run_safely(call_id))


async def _run_safely(call_id: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        async with SessionLocal() as db:
            result = await analyze_call(db, call_id=call_id, analysis_model=settings.analysis_model)
            # If the agent version has a server_url, enqueue analysis.completed.
            call = (await db.execute(select(Call).where(Call.id == call_id))).scalar_one_or_none()
            if call and call.agent_version_id:
                ver = await db.get(AgentVersion, call.agent_version_id)
                if ver is not None and ver.server_url:
                    await webhook_dispatcher.enqueue(
                        db,
                        org_id=call.org_id,
                        url=ver.server_url,
                        event="analysis.completed",
                        payload={
                            "call_id": call.id,
                            "agent_id": call.agent_id,
                            "analysis": result,
                        },
                    )
            return result
    except Exception as exc:
        log.exception("analysis.scheduler.err", call=call_id, err=str(exc))
        return None
