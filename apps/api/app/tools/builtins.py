"""Built-in tool registry.

Definitions are LLM-tool-call shaped (OpenAI tool schema). Handlers receive
a ToolContext with the call object, db session, and telnyx client; they may
mutate call state, dispatch DTMF/transfer/hangup, or extract structured data.
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
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
                at=datetime.now(timezone.utc),
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
    ctx.call.ended_at = datetime.now(timezone.utc)
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
        await ctx.telnyx.transfer(
            ctx.call.provider_call_id, to=to, from_=ctx.call.to_number
        )
    return {"transferred_to": to, "summary": summary}


async def _send_dtmf(ctx: ToolContext) -> dict[str, Any]:
    digits = (ctx.args or {}).get("digits", "")
    if not digits:
        return {"error": "missing_digits"}
    if ctx.telnyx and ctx.call.provider_call_id:
        await ctx.telnyx.send_dtmf(ctx.call.provider_call_id, digits)
    return {"sent": digits}


async def _leave_voicemail(ctx: ToolContext) -> dict[str, Any]:
    # Real impl: synth TTS, play once, then hangup. Stubbed for v1.
    msg = (ctx.args or {}).get("message", "")
    return {"left": True, "message": msg[:200]}


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
