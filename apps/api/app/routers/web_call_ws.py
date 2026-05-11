"""Browser WebSocket transport for a web call.

Wire protocol:

Client → server:
  - Binary frames: PCM 16-bit LE mono @ <cfg.sample_rate> (default 16 kHz).
  - Text JSON: {"type":"user_text","text":"...","is_final":true}
                — text-mode override, bypasses STT.
                {"type":"hangup"} — end the session cleanly.

Server → client:
  - Binary frames: PCM agent audio (same encoding).
  - Text JSON events (PipelineEvent serialised):
      {"type":"started"|"user_text"|"agent_text"|"tool_call"|
              "tool_result"|"turn_end"|"error"|"stt", ...}
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import AgentVersion, Call, CallEvent, CallStatus
from app.db.session import SessionLocal
from app.pipeline import event_bus
from app.pipeline.orchestrator import AgentConfig, Pipeline, PipelineEvent, ToolCall
from app.pipeline.stt import DeepgramStream
from app.pipeline.web_session import verify_ws_token
from app.tools.builtins import REGISTRY, ToolContext

router = APIRouter(prefix="/v1/calls", tags=["calls"])


@router.websocket("/{call_id}/ws")
async def web_call_ws(
    ws: WebSocket,
    call_id: str,
    token: str = Query(...),
    text_only: bool = Query(False, description="Skip STT — text-mode only."),
) -> None:
    if not verify_ws_token(call_id, token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    async with SessionLocal() as db:
        call = await _load_call(db, call_id)
        if not call:
            await ws.send_json({"type": "error", "error": "call_not_found"})
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        cfg = await _build_agent_config(db, call)
        if cfg is None:
            await ws.send_json({"type": "error", "error": "agent_version_missing"})
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        call.status = CallStatus.in_progress
        call.started_at = datetime.now(UTC)
        await db.commit()

        await _run_session(ws, db, call, cfg, text_only=text_only)


# ---------------------------------------------------------------------------

async def _load_call(db: AsyncSession, call_id: str) -> Call | None:
    return (
        await db.execute(select(Call).where(Call.id == call_id))
    ).scalar_one_or_none()


async def _build_agent_config(db: AsyncSession, call: Call) -> AgentConfig | None:
    if not call.agent_version_id:
        # No published version — fall back to latest
        latest = (
            await db.execute(
                select(AgentVersion)
                .where(AgentVersion.agent_id == call.agent_id)
                .order_by(AgentVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        ver = latest
    else:
        ver = (
            await db.execute(
                select(AgentVersion).where(AgentVersion.id == call.agent_version_id)
            )
        ).scalar_one_or_none()
    if ver is None:
        return None

    tool_defs = _resolve_tools(ver)

    return AgentConfig(
        model_id=ver.model_id,
        voice_id=ver.voice_id,
        system_prompt=ver.system_prompt or "",
        first_message=ver.first_message,
        tools=tool_defs,
        knowledge_base_ids=list(ver.knowledge_base_ids or []),
    )


def _resolve_tools(ver: AgentVersion) -> list[dict]:
    """Resolve tool refs to OpenAI tool schemas, auto-binding kb_lookup when
    the agent has bound KBs or its flow graph references kb_lookup nodes."""
    tool_defs: list[dict] = []
    seen: set[str] = set()

    def _add(defn: dict) -> None:
        name = defn.get("function", {}).get("name")
        if name and name not in seen:
            tool_defs.append(defn)
            seen.add(name)

    for t in ver.tools or []:
        if isinstance(t, dict) and t.get("type") == "function":
            _add(t)
        elif isinstance(t, dict) and "name" in t:
            entry = REGISTRY.get(t["name"])
            if entry:
                _add(entry["definition"])
        elif isinstance(t, str):
            entry = REGISTRY.get(t)
            if entry:
                _add(entry["definition"])

    has_kb = bool(ver.knowledge_base_ids)
    graph = ver.flow_graph or {}
    if not has_kb and isinstance(graph, dict):
        for n in graph.get("nodes") or []:
            data = n.get("data") if isinstance(n, dict) else None
            if isinstance(data, dict) and data.get("kind") == "kb_lookup":
                has_kb = True
                break
    if has_kb:
        kb_entry = REGISTRY.get("kb_lookup")
        if kb_entry:
            _add(kb_entry["definition"])

    return tool_defs


async def _run_session(
    ws: WebSocket,
    db: AsyncSession,
    call: Call,
    cfg: AgentConfig,
    *,
    text_only: bool,
) -> None:
    async def tool_dispatch(tc: ToolCall) -> dict[str, Any]:
        entry = REGISTRY.get(tc.name)
        if not entry:
            return {"error": "unknown_tool", "name": tc.name}
        ctx = ToolContext(
            call=call,
            db=db,
            telnyx=None,
            args=tc.arguments,
            knowledge_base_ids=list(cfg.knowledge_base_ids or []),
            embedding_model=cfg.embedding_model,
        )
        try:
            return await entry["handler"](ctx)
        except Exception as exc:
            log.exception("ws.tool.error", name=tc.name, err=str(exc))
            return {"error": "tool_failed", "detail": str(exc)}

    pipe = Pipeline(cfg, tool_dispatch=tool_dispatch)

    stt_stream: DeepgramStream | None = None
    stt_pusher_task: asyncio.Task | None = None
    transcript_log: list[dict] = []

    if not text_only:
        try:
            stt_stream = DeepgramStream(sample_rate=cfg.sample_rate)
            await stt_stream.__aenter__()
        except Exception as exc:
            log.warning("ws.stt.unavailable", err=str(exc))
            await ws.send_json({"type": "warn", "warn": "stt_unavailable", "detail": str(exc)})
            stt_stream = None

        if stt_stream is not None:
            async def _stt_pump() -> None:
                buf = ""
                assert stt_stream is not None
                async for ev in stt_stream.events():
                    if ev.text:
                        buf = ev.text if ev.is_final else buf
                        await ws.send_json({
                            "type": "stt",
                            "text": ev.text,
                            "is_final": ev.is_final,
                            "speech_final": ev.speech_final,
                        })
                    if ev.speech_final and buf:
                        await pipe.feed_user_text(buf, is_final=True)
                        transcript_log.append({"role": "user", "text": buf})
                        buf = ""

            stt_pusher_task = asyncio.create_task(_stt_pump())

    async def _drain_pipeline() -> None:
        async for ev in pipe.events():
            await _emit(ws, ev, transcript_log, call.id)

    drainer = asyncio.create_task(_drain_pipeline())

    try:
        await pipe.start()
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                if stt_stream is not None:
                    await stt_stream.push(msg["bytes"])
                continue
            if "text" in msg and msg["text"]:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                mtype = data.get("type")
                if mtype == "user_text":
                    text = data.get("text") or ""
                    is_final = bool(data.get("is_final", True))
                    if text:
                        await pipe.feed_user_text(text, is_final=is_final)
                        if is_final:
                            transcript_log.append({"role": "user", "text": text})
                elif mtype == "hangup":
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("ws.session.error", err=str(exc))
    finally:
        if stt_pusher_task:
            stt_pusher_task.cancel()
        if stt_stream:
            await stt_stream.close()
        await pipe.close()
        drainer.cancel()
        event_bus.close(call.id)
        await _finalise_call(db, call, transcript_log)
        try:
            await ws.close()
        except Exception:
            pass


async def _emit(ws: WebSocket, ev: PipelineEvent, log_buf: list[dict], call_id: str) -> None:
    try:
        if ev.kind == "agent_audio" and ev.audio:
            await ws.send_bytes(ev.audio)
            return
        payload: dict[str, Any] = {"type": ev.kind}
        if ev.text is not None:
            payload["text"] = ev.text
        if ev.is_final:
            payload["is_final"] = True
        if ev.data is not None:
            payload["data"] = ev.data
        await ws.send_json(payload)
        # Fan out to spectator subscribers (SSE etc.). Audio frames are
        # excluded — too heavy and not useful in JSON streams.
        event_bus.publish(call_id, payload)
        if ev.kind == "agent_text" and ev.text:
            log_buf.append({"role": "assistant", "text": ev.text})
    except Exception as exc:
        log.warning("ws.emit.error", err=str(exc))


async def _finalise_call(db: AsyncSession, call: Call, transcript: list[dict]) -> None:
    try:
        now = datetime.now(UTC)
        if call.status != CallStatus.completed:
            call.status = CallStatus.completed
        call.ended_at = now
        if call.started_at:
            call.duration_ms = int((now - call.started_at).total_seconds() * 1000)
        call.transcript = transcript or call.transcript
        db.add(CallEvent(call_id=call.id, at=now, kind="ws.closed", payload={"turns": len(transcript)}))
        await db.commit()
    except Exception as exc:
        log.warning("ws.finalise.error", err=str(exc))
