"""Console aggregation endpoint.

Returns the data each Launch Console card needs in a single call. Cheaper than
chatty per-card endpoints and keeps the frontend stateless about wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthedPrincipal, require_principal
from app.db.models import (
    Agent,
    AgentVersion,
    Call,
    CallEvent,
    CallStatus,
    KnowledgeBase,
    PhoneNumber,
)
from app.db.session import get_db

router = APIRouter(prefix="/v1/console", tags=["console"])


@router.get("/summary")
async def console_summary(
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> dict[str, Any]:
    org_id = p.org.id

    has_phone = bool(
        (
            await db.execute(select(PhoneNumber.id).where(PhoneNumber.org_id == org_id).limit(1))
        ).first()
    )
    has_kb = bool(
        (
            await db.execute(
                select(KnowledgeBase.id).where(KnowledgeBase.org_id == org_id).limit(1)
            )
        ).first()
    )
    agents = (await db.execute(select(Agent).where(Agent.org_id == org_id))).scalars().all()
    has_agent = bool(agents)
    has_published = any(a.published_version_id for a in agents)

    # Look at the published version of each agent for richer checklist signals
    pub_ids = [a.published_version_id for a in agents if a.published_version_id]
    pubs: list[AgentVersion] = []
    if pub_ids:
        pubs = list(
            (await db.execute(select(AgentVersion).where(AgentVersion.id.in_(pub_ids))))
            .scalars()
            .all()
        )
    has_voice = any(bool(v.voice_id) for v in pubs) or has_agent
    has_guardrails = any(bool((v.system_prompt or "").strip()) for v in pubs)
    has_tools = any(bool(v.tools) for v in pubs)

    def step(key: str, label: str, ok: bool, current: bool = False) -> dict[str, str]:
        return {
            "key": key,
            "label": label,
            "status": "done" if ok else ("current" if current else "todo"),
        }

    # First incomplete step is "current"
    raw = [
        ("phone", "Phone Number", has_phone),
        ("kb", "Knowledge Base", has_kb),
        ("voice", "Voice", has_voice),
        ("guardrails", "Guardrails", has_guardrails),
        ("tools", "Tools", has_tools),
        ("launch", "Launch", has_published),
    ]
    current_key: str | None = next((k for k, _, ok in raw if not ok), None)
    checklist = [step(k, label, ok, current=(k == current_key)) for k, label, ok in raw]

    # --- today rollup ------------------------------------------------------
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yest_start = today_start - timedelta(days=1)

    today_rows = (
        await db.execute(
            select(Call.status, Call.duration_ms).where(
                Call.org_id == org_id, Call.created_at >= today_start
            )
        )
    ).all()
    today_count = len(today_rows)
    today_completed = sum(1 for s, _ in today_rows if s == CallStatus.completed)
    today_failed = sum(1 for s, _ in today_rows if s == CallStatus.failed)
    today_dur = [d for _, d in today_rows if d]
    today_avg_ms = int(sum(today_dur) / len(today_dur)) if today_dur else 0

    yest_count = (
        await db.execute(
            select(func.count(Call.id)).where(
                Call.org_id == org_id,
                Call.created_at >= yest_start,
                Call.created_at < today_start,
            )
        )
    ).scalar_one() or 0

    today = {
        "calls": today_count,
        "completed": today_completed,
        "failed": today_failed,
        "avg_duration_ms": today_avg_ms,
        "calls_delta_vs_yesterday": today_count - int(yest_count),
    }

    # --- recent tool calls -------------------------------------------------
    tool_rows = (
        await db.execute(
            select(CallEvent.id, CallEvent.kind, CallEvent.payload, CallEvent.at, CallEvent.call_id)
            .join(Call, Call.id == CallEvent.call_id)
            .where(Call.org_id == org_id, CallEvent.kind.like("tool.%"))
            .order_by(CallEvent.at.desc())
            .limit(20)
        )
    ).all()
    recent_tool_calls = []
    for row in tool_rows:
        payload = row.payload or {}
        result = payload.get("result") or {}
        ok = isinstance(result, dict) and "error" not in result
        recent_tool_calls.append(
            {
                "id": str(row.id),
                "name": row.kind.removeprefix("tool."),
                "status": "success" if ok else "failed",
                "call_id": row.call_id,
                "at": row.at.isoformat(),
            }
        )

    # --- launch history ----------------------------------------------------
    launches_rows = (
        await db.execute(
            select(
                AgentVersion.id,
                AgentVersion.version,
                AgentVersion.env,
                AgentVersion.created_at,
                Agent.name,
                Agent.id,
            )
            .join(Agent, Agent.id == AgentVersion.agent_id)
            .where(Agent.org_id == org_id, AgentVersion.env != "draft")
            .order_by(AgentVersion.created_at.desc())
            .limit(10)
        )
    ).all()
    launch_history = [
        {
            "id": r[0],
            "version": f"v{r[1]}",
            "env": r[2],
            "date": r[3].strftime("%b %d, %Y"),
            "agent_id": r[5],
            "agent_name": r[4],
            "status": "live" if r[2] == "production" else "archived",
        }
        for r in launches_rows
    ]

    # --- score breakdown (derived from analysis JSON when present) ---------
    analyzed = (
        await db.execute(
            select(Call.analysis).where(
                Call.org_id == org_id,
                Call.analysis.isnot(None),
                Call.created_at >= today_start - timedelta(days=7),
            )
        )
    ).all()
    score_breakdown = _aggregate_scores([row[0] for row in analyzed if row[0]])

    # --- compliance flags (config-derived, not org-stored yet) -------------
    compliance = [
        {"key": "pii", "label": "PII Redaction", "status": "ok"},
        {"key": "rec", "label": "Call Recording", "status": "ok"},
        {"key": "consent", "label": "2-party consent", "status": "warn"},
        {"key": "hipaa", "label": "HIPAA mode", "status": "off"},
    ]

    return {
        "checklist": checklist,
        "today": today,
        "recent_tool_calls": recent_tool_calls,
        "launch_history": launch_history,
        "score_breakdown": score_breakdown,
        "compliance": compliance,
    }


_ANALYTICS_RANGES = {"7d": 7, "30d": 30, "90d": 90}


@router.get("/analytics")
async def console_analytics(
    range_: str = Query("7d", alias="range"),
    db: AsyncSession = Depends(get_db),
    p: AuthedPrincipal = Depends(require_principal),
) -> dict[str, Any]:
    """Aggregated call analytics for the Analytics page.

    `range` query param ∈ 7d/30d/90d. Anything else falls back to 7d.
    """
    org_id = p.org.id
    days = _ANALYTICS_RANGES.get(range_, 7)
    range_key = range_ if range_ in _ANALYTICS_RANGES else "7d"

    now = datetime.now(UTC)
    since = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # --- per-day volume ----------------------------------------------------
    day_bucket = func.date_trunc("day", Call.created_at)
    completed_status = CallStatus.completed.value
    failed_status = CallStatus.failed.value

    # Success expression: prefer the structured analysis verdict from the
    # post-call run; fall back to status=completed when no verdict is logged.
    # `analysis -> 'success_evaluation' ->> 'success'` materializes the inner
    # JSON scalar as text in Postgres so we can compare it cheaply.
    success_text = (
        Call.analysis[("success_evaluation", "success")].astext  # type: ignore[index]
    )
    success_expr = case(
        (success_text == "true", 1),
        (success_text == "false", 0),
        (Call.status == completed_status, 1),
        else_=0,
    )
    day_rows = (
        await db.execute(
            select(
                day_bucket.label("day"),
                func.count(Call.id).label("count"),
                func.count(Call.id).filter(Call.status == completed_status).label("completed"),
                func.count(Call.id).filter(Call.status == failed_status).label("failed"),
            )
            .where(Call.org_id == org_id, Call.created_at >= since)
            .group_by(day_bucket)
            .order_by(day_bucket)
        )
    ).all()

    # Fill missing days with zeros so the chart x-axis is uniform.
    by_day_map: dict[str, dict[str, Any]] = {}
    for r in day_rows:
        d = r.day.date() if hasattr(r.day, "date") else r.day
        by_day_map[d.isoformat()] = {
            "date": d.isoformat(),
            "count": int(r.count or 0),
            "completed": int(r.completed or 0),
            "failed": int(r.failed or 0),
        }
    volume_by_day: list[dict[str, Any]] = []
    for i in range(days):
        d = (since + timedelta(days=i)).date()
        key = d.isoformat()
        volume_by_day.append(
            by_day_map.get(key, {"date": key, "count": 0, "completed": 0, "failed": 0})
        )

    # --- duration stats ----------------------------------------------------
    dur_row = (
        await db.execute(
            select(
                func.avg(Call.duration_ms).label("avg"),
                func.percentile_cont(0.5).within_group(Call.duration_ms.asc()).label("p50"),
                func.percentile_cont(0.95).within_group(Call.duration_ms.asc()).label("p95"),
            ).where(
                Call.org_id == org_id,
                Call.created_at >= since,
                Call.duration_ms.isnot(None),
            )
        )
    ).one()
    avg_duration_ms = int(dur_row.avg) if dur_row.avg else 0
    p50_duration_ms = int(dur_row.p50) if dur_row.p50 else 0
    p95_duration_ms = int(dur_row.p95) if dur_row.p95 else 0

    # total + success use the unfiltered set (includes calls with no duration)
    totals_row = (
        await db.execute(
            select(
                func.count(Call.id).label("total"),
                func.coalesce(func.sum(success_expr), 0).label("success_count"),
            ).where(Call.org_id == org_id, Call.created_at >= since)
        )
    ).one()
    total_calls = int(totals_row.total or 0)
    total_success = int(totals_row.success_count or 0)
    success_rate = (total_success / total_calls) if total_calls else 0.0

    # --- per-agent breakdown ----------------------------------------------
    agent_rows = (
        await db.execute(
            select(
                Agent.id,
                Agent.name,
                func.count(Call.id).label("count"),
                func.coalesce(func.sum(success_expr), 0).label("success_count"),
            )
            .join(Call, Call.agent_id == Agent.id)
            .where(Agent.org_id == org_id, Call.created_at >= since)
            .group_by(Agent.id, Agent.name)
            .order_by(func.count(Call.id).desc())
            .limit(10)
        )
    ).all()
    by_agent = [
        {
            "agent_id": r.id,
            "name": r.name,
            "count": int(r.count or 0),
            "success_rate": (int(r.success_count) / int(r.count) if r.count else 0.0),
        }
        for r in agent_rows
    ]

    return {
        "range": range_key,
        "volume_by_day": volume_by_day,
        "by_agent": by_agent,
        "total_calls": total_calls,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": p50_duration_ms,
        "p95_duration_ms": p95_duration_ms,
        "success_rate": success_rate,
    }


def _aggregate_scores(analyses: list[dict]) -> list[dict[str, Any]]:
    """Average each known score axis across the provided analyses.

    Falls back to neutral placeholder values when no analysis rows exist.
    """
    keys = ("knowledge", "latency", "empathy", "compliance")
    if not analyses:
        return [
            {"key": "knowledge", "label": "Knowledge", "value": 0},
            {"key": "latency", "label": "Latency", "value": 0},
            {"key": "empathy", "label": "Empathy", "value": 0},
            {"key": "compliance", "label": "Compliance", "value": 0},
        ]
    sums: dict[str, float] = dict.fromkeys(keys, 0.0)
    counts: dict[str, int] = dict.fromkeys(keys, 0)
    for a in analyses:
        scores = a.get("scores") if isinstance(a, dict) else None
        if not isinstance(scores, dict):
            continue
        for k in keys:
            v = scores.get(k)
            if isinstance(v, (int, float)):
                sums[k] += float(v)
                counts[k] += 1
    return [
        {
            "key": k,
            "label": k.capitalize(),
            "value": int(sums[k] / counts[k]) if counts[k] else 0,
        }
        for k in keys
    ]
