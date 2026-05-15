"""Built-in tool registry.

Definitions are LLM-tool-call shaped (OpenAI tool schema). Handlers receive
a ToolContext with the call object, db session, and telnyx client; they may
mutate call state, dispatch DTMF/transfer/hangup, or extract structured data.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import Call, CallEvent, CallStatus
from app.telephony.telnyx import TelnyxClient


@dataclass
class ToolContext:
    call: Call
    db: AsyncSession
    telnyx: TelnyxClient | None = None
    args: dict[str, Any] | None = None
    knowledge_base_ids: list[str] | None = None
    embedding_model: str = "text-embedding-3-small"


Handler = Callable[[ToolContext], Awaitable[dict[str, Any]]]

REGISTRY: dict[str, dict[str, Any]] = {}


def register(name: str, *, definition: dict[str, Any], handler: Handler) -> None:
    REGISTRY[name] = {"definition": definition, "handler": handler}


async def dispatch(name: str, ctx: ToolContext) -> dict[str, Any]:
    entry = REGISTRY.get(name)
    if not entry:
        return {"error": f"unknown_tool:{name}"}
    try:
        result = await entry["handler"](ctx)
        ctx.db.add(
            CallEvent(
                call_id=ctx.call.id,
                at=datetime.now(UTC),
                kind=f"tool.{name}",
                payload={"args": ctx.args, "result": result},
            )
        )
        await ctx.db.commit()
        return result
    except Exception as exc:
        log.exception("tool.error", name=name, err=str(exc))
        return {"error": "tool_failed", "detail": str(exc)}


# --- Definitions ---------------------------------------------------------


def _def(name: str, description: str, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": params, "required": []},
        },
    }


# --- Handlers ------------------------------------------------------------


async def _end_call(ctx: ToolContext) -> dict[str, Any]:
    ctx.call.status = CallStatus.completed
    ctx.call.ended_at = datetime.now(UTC)
    if ctx.telnyx and ctx.call.provider_call_id:
        await ctx.telnyx.hangup(ctx.call.provider_call_id)
    return {"status": "ended"}


async def _transfer_call(ctx: ToolContext) -> dict[str, Any]:
    args = ctx.args or {}
    to = args.get("to")
    summary = args.get("summary", "")
    if not to:
        return {"error": "missing_to"}
    if ctx.telnyx and ctx.call.provider_call_id and ctx.call.to_number:
        await ctx.telnyx.transfer(ctx.call.provider_call_id, to=to, from_=ctx.call.to_number)
    return {"transferred_to": to, "summary": summary}


async def _send_dtmf(ctx: ToolContext) -> dict[str, Any]:
    digits = (ctx.args or {}).get("digits", "")
    if not digits:
        return {"error": "missing_digits"}
    if ctx.telnyx and ctx.call.provider_call_id:
        await ctx.telnyx.send_dtmf(ctx.call.provider_call_id, digits)
    return {"sent": digits}


async def _leave_voicemail(ctx: ToolContext) -> dict[str, Any]:
    """End the call after caller-side TTS has spoken the voicemail message.

    The LLM is expected to speak the message in the same turn (its text
    becomes audio via the live TTS path). After this returns, the conversation
    loop terminates. For PSTN calls, also instruct the carrier to hang up.
    """
    msg = str((ctx.args or {}).get("message") or "")
    msg = msg[:1000]

    # Persist on the call row so downstream analytics see "voicemail left".
    new_vars = dict(ctx.call.dynamic_variables or {})
    new_vars["voicemail_message"] = msg
    new_vars["voicemail_left_at"] = datetime.now(UTC).isoformat()
    ctx.call.dynamic_variables = new_vars

    # Mark call completed (mirrors end_call semantics).
    ctx.call.status = CallStatus.completed
    ctx.call.ended_at = datetime.now(UTC)

    # PSTN: tell Telnyx to drop the leg.
    if ctx.telnyx and ctx.call.provider_call_id:
        try:
            await ctx.telnyx.hangup(ctx.call.provider_call_id)
        except Exception as exc:
            log.warning("voicemail.telnyx_hangup_error", err=str(exc))

    return {"left": True, "message": msg, "ended": True}


async def _kb_lookup(ctx: ToolContext) -> dict[str, Any]:
    """Semantic search over one of the agent's bound knowledge bases."""
    from app.kb.store import search as kb_search

    args = ctx.args or {}
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "missing_query"}
    requested = args.get("kb_id")
    available = ctx.knowledge_base_ids or []
    kb_id: str | None = None
    if requested and requested in available:
        kb_id = requested
    elif available:
        kb_id = available[0]
    if not kb_id:
        return {"error": "no_kb_bound"}
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 20))
    hits = await kb_search(
        ctx.db, kb_id=kb_id, query=query, embedding_model=ctx.embedding_model, k=top_k
    )
    return {
        "kb_id": kb_id,
        "query": query,
        "hits": [
            {"chunk_id": h.chunk_id, "source_id": h.source_id, "score": h.score, "text": h.text}
            for h in hits
        ],
    }


async def _book_meeting(ctx: ToolContext) -> dict[str, Any]:
    """Book a calendar event.

    Resolution order:
      1. Per-org OAuth integration (user connected via /settings/integrations)
      2. Env-configured service account (headless / fallback)

    Args (LLM-supplied): title, start_iso, attendee_email, duration_min?, description?
    Returns: {event_id, html_link, start, end} on success; {error: ...} otherwise.
    """
    from app.tools.calendar import book_event, book_event_for_org

    args = ctx.args or {}
    title = (args.get("title") or "").strip()
    start_iso = (args.get("start_iso") or "").strip()
    if not title:
        return {"error": "missing_title"}
    if not start_iso:
        return {"error": "missing_start_iso"}
    common = {
        "title": title,
        "start_iso": start_iso,
        "attendee_email": (args.get("attendee_email") or None),
        "duration_min": (args.get("duration_min") or None),
        "description": (args.get("description") or None),
    }
    # Live-call path: ctx.call carries org_id → use per-org OAuth integration.
    # Headless / test path: no call attached → fall back to SA-from-env.
    if ctx.call is not None and ctx.db is not None:
        return await book_event_for_org(db=ctx.db, org_id=ctx.call.org_id, **common)
    return await book_event(**common)


async def _extract_data(ctx: ToolContext) -> dict[str, Any]:
    args = ctx.args or {}
    # Caller-provided values stored on dynamic_variables for downstream use.
    new_vars = dict(ctx.call.dynamic_variables or {})
    extracted = args.get("data") or {}
    if not isinstance(extracted, dict):
        try:
            extracted = json.loads(extracted)
        except Exception:
            return {"error": "data_not_object"}
    new_vars.update(extracted)
    ctx.call.dynamic_variables = new_vars
    return {"extracted": extracted}


register(
    "end_call",
    definition=_def("end_call", "End the call gracefully.", {}),
    handler=_end_call,
)
register(
    "transfer_call",
    definition=_def(
        "transfer_call",
        "Transfer the live call to another PSTN number, optionally with a warm-handoff summary.",
        {
            "to": {"type": "string", "description": "E.164 destination number"},
            "summary": {"type": "string", "description": "One-line context for the human"},
        },
    ),
    handler=_transfer_call,
)
register(
    "send_dtmf",
    definition=_def(
        "send_dtmf",
        "Send DTMF digits down the call (e.g. to navigate an IVR).",
        {"digits": {"type": "string", "description": "Digits to send, e.g. '1234#'"}},
    ),
    handler=_send_dtmf,
)
register(
    "leave_voicemail",
    definition=_def(
        "leave_voicemail",
        "Detected voicemail. Leave a message, then end the call.",
        {"message": {"type": "string", "description": "Message text to speak"}},
    ),
    handler=_leave_voicemail,
)
register(
    "kb_lookup",
    definition=_def(
        "kb_lookup",
        "Search the agent's knowledge base for passages relevant to a natural-language query. Returns the top-k matching chunks with similarity scores.",
        {
            "query": {"type": "string", "description": "Natural-language query"},
            "kb_id": {
                "type": "string",
                "description": "Optional: which bound KB to search. Defaults to the agent's first bound KB.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max results to return (1–20, default 5).",
            },
        },
    ),
    handler=_kb_lookup,
)
register(
    "book_meeting",
    definition=_def(
        "book_meeting",
        "Book a calendar event on the configured Google calendar. Use when the caller agrees to a specific time. Always pass an ISO-8601 start (UTC or with offset).",
        {
            "title": {"type": "string", "description": "Event title"},
            "start_iso": {
                "type": "string",
                "description": "ISO-8601 start time, e.g. 2026-05-15T15:00:00-07:00",
            },
            "attendee_email": {
                "type": "string",
                "description": "Email of the person to invite (optional)",
            },
            "duration_min": {
                "type": "integer",
                "description": "Override default meeting length (minutes)",
            },
            "description": {"type": "string", "description": "Free-text agenda"},
        },
    ),
    handler=_book_meeting,
)
register(
    "extract_data",
    definition=_def(
        "extract_data",
        "Persist structured caller-supplied data into the call dynamic_variables.",
        {"data": {"type": "object", "description": "JSON object of fields to merge"}},
    ),
    handler=_extract_data,
)


def builtin_definitions() -> list[dict[str, Any]]:
    return [entry["definition"] for entry in REGISTRY.values()]
