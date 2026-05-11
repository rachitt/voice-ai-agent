"""Post-call analysis: summary + structured_data + success_evaluation.

Invoked async after `call.ended`. Writes back to Call.analysis JSONB and
emits an `analysis.completed` webhook (caller wires the outbox).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import Call
from app.pipeline.llm import Message, complete

DEFAULT_SUMMARY_PROMPT = (
    "Summarize this voice agent call in 2-3 sentences. Mention caller intent, "
    "what the agent did, and outcome."
)
DEFAULT_SUCCESS_PROMPT = (
    "Did the agent successfully address the caller's request? "
    "Respond with strict JSON: {\"success\": boolean, \"reason\": string}."
)


def _format_transcript(transcript: list[dict[str, Any]] | None) -> str:
    if not transcript:
        return "(empty)"
    return "\n".join(
        f"[{line.get('who','agent')}] {line.get('text','')}" for line in transcript
    )


async def _run_summary(model_id: str, transcript: str, prompt: str) -> str:
    resp = await complete(
        model_id=model_id,
        messages=[
            Message(role="system", content=prompt),
            Message(role="user", content=transcript),
        ],
        temperature=0.2,
    )
    return resp["choices"][0]["message"]["content"].strip()


async def _run_structured(
    model_id: str, transcript: str, schema: dict[str, Any]
) -> dict[str, Any]:
    sys = (
        "Extract data from this call transcript and return ONLY valid JSON "
        f"matching this schema: {json.dumps(schema)}"
    )
    resp = await complete(
        model_id=model_id,
        messages=[
            Message(role="system", content=sys),
            Message(role="user", content=transcript),
        ],
        temperature=0.0,
    )
    raw = resp["choices"][0]["message"]["content"]
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("analysis.structured.bad_json", err=str(exc), raw=raw[:200])
        return {"_error": "bad_json", "_raw": raw[:1000]}


async def _run_success(model_id: str, transcript: str, prompt: str) -> dict[str, Any]:
    resp = await complete(
        model_id=model_id,
        messages=[
            Message(role="system", content=prompt),
            Message(role="user", content=transcript),
        ],
        temperature=0.0,
    )
    raw = resp["choices"][0]["message"]["content"]
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"success": False, "reason": "could_not_parse"}


async def analyze_call(
    db: AsyncSession,
    *,
    call_id: str,
    analysis_model: str = "gemini-2.0-flash",
) -> dict[str, Any]:
    call = (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()
    if not call:
        raise LookupError(f"call {call_id} not found")

    transcript_text = _format_transcript(call.transcript)
    plan = (call.analysis or {}).get("plan") if call.analysis else None
    plan = plan or {}

    out: dict[str, Any] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "model": analysis_model,
    }

    out["summary"] = await _run_summary(
        analysis_model, transcript_text, plan.get("summary_prompt") or DEFAULT_SUMMARY_PROMPT
    )

    schema = plan.get("structured_data_schema")
    if schema:
        out["structured_data"] = await _run_structured(
            analysis_model, transcript_text, schema
        )

    out["success_evaluation"] = await _run_success(
        analysis_model,
        transcript_text,
        plan.get("success_prompt") or DEFAULT_SUCCESS_PROMPT,
    )

    call.analysis = out
    await db.commit()
    log.info("analysis.done", call=call_id)
    return out
