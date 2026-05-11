"""Telnyx Media Streaming WebSocket bridge.

Telnyx connects to us at `wss://<public>/v1/telephony/telnyx/media?call_id=…&token=…`
and exchanges JSON envelopes carrying base64-encoded μ-law audio:

  { "event": "start", "start": {"streamId": "...", "callSid": "..."} }
  { "event": "media", "media": {"payload": "<base64 μ-law 8 kHz mono>"} }
  { "event": "stop" }

We transcode that to/from linear16 @ 16 kHz so it flows through the same
Pipeline + tool dispatch as a browser web-call.
"""
from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import log
from app.db.models import Call, CallEvent, CallStatus
from app.db.session import SessionLocal
from app.pipeline import event_bus
from app.pipeline.orchestrator import AgentConfig, Pipeline, PipelineEvent, ToolCall
from app.pipeline.stt import DeepgramStream
from app.pipeline.web_session import verify_ws_token
from app.routers.web_call_ws import _build_agent_config  # reuse
from app.telephony.audio import pcm16_16k_to_ulaw, ulaw_to_pcm16_16k
from app.telephony.telnyx import TelnyxClient
from app.tools.builtins import REGISTRY, ToolContext

router = APIRouter(prefix="/v1/telephony", tags=["telephony"])


@router.websocket("/telnyx/media")
async def telnyx_media(
    ws: WebSocket,
    call_id: str = Query(..., alias="call_id"),
    token: str = Query(...),
) -> None:
    if not verify_ws_token(call_id, token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await ws.accept()

    async with SessionLocal() as db:
        call = (
            await db.execute(select(Call).where(Call.id == call_id))
        ).scalar_one_or_none()
        if not call:
            await ws.send_json({"event": "error", "error": "call_not_found"})
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        cfg = await _build_agent_config(db, call)
        if cfg is None:
            await ws.send_json({"event": "error", "error": "agent_version_missing"})
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if call.status != CallStatus.in_progress:
            call.status = CallStatus.in_progress
            call.started_at = call.started_at or datetime.now(UTC)
            await db.commit()

        await _run_pstn_session(ws, db, call, cfg)


async def _run_pstn_session(ws: WebSocket, db: AsyncSession, call: Call, cfg: AgentConfig) -> None:
    telnyx = TelnyxClient()

    async def tool_dispatch(tc: ToolCall) -> dict[str, Any]:
        entry = REGISTRY.get(tc.name)
        if not entry:
            return {"error": "unknown_tool", "name": tc.name}
        ctx = ToolContext(call=call, db=db, telnyx=telnyx, args=tc.arguments)
        try:
            return await entry["handler"](ctx)
        except Exception as exc:
            log.exception("telnyx.tool.error", name=tc.name, err=str(exc))
            return {"error": "tool_failed", "detail": str(exc)}

    pipe = Pipeline(cfg, tool_dispatch=tool_dispatch)
    transcript_log: list[dict] = []
    stream_id: str | None = None

    stt: DeepgramStream | None = None
    try:
        stt = DeepgramStream(sample_rate=cfg.sample_rate)
        await stt.__aenter__()
    except Exception as exc:
        log.warning("telnyx.stt.unavailable", err=str(exc))
        stt = None

    async def _stt_pump() -> None:
        assert stt is not None
        buf = ""
        async for ev in stt.events():
            if ev.text and ev.is_final:
                buf = ev.text
            if ev.speech_final and buf:
                await pipe.feed_user_text(buf, is_final=True)
                transcript_log.append({"role": "user", "text": buf})
                buf = ""

    stt_task = asyncio.create_task(_stt_pump()) if stt is not None else None

    async def _drain_pipeline() -> None:
        async for ev in pipe.events():
            await _emit_pstn(ws, ev, stream_id, call.id, transcript_log)

    drainer = asyncio.create_task(_drain_pipeline())

    try:
        await pipe.start()
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            evt = data.get("event")
            if evt == "start":
                stream_id = (data.get("start") or {}).get("streamId")
                call.provider_call_id = (data.get("start") or {}).get("callSid") or call.provider_call_id
            elif evt == "media":
                payload = ((data.get("media") or {}).get("payload")) or ""
                if not payload or stt is None:
                    continue
                try:
                    ulaw = base64.b64decode(payload)
                    pcm = ulaw_to_pcm16_16k(ulaw)
                except Exception as exc:
                    log.warning("telnyx.decode.err", err=str(exc))
                    continue
                await stt.push(pcm)
            elif evt == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("telnyx.session.error", err=str(exc))
    finally:
        if stt_task:
            stt_task.cancel()
        if stt is not None:
            await stt.close()
        await pipe.close()
        drainer.cancel()
        event_bus.close(call.id)
        await _finalise(db, call, transcript_log)
        await telnyx.aclose()
        try:
            await ws.close()
        except Exception:
            pass


async def _emit_pstn(
    ws: WebSocket,
    ev: PipelineEvent,
    stream_id: str | None,
    call_id: str,
    transcript_log: list[dict],
) -> None:
    try:
        if ev.kind == "agent_audio" and ev.audio:
            ulaw = pcm16_16k_to_ulaw(ev.audio)
            envelope = {
                "event": "media",
                "streamId": stream_id or "",
                "media": {"payload": base64.b64encode(ulaw).decode("ascii")},
            }
            await ws.send_text(json.dumps(envelope))
            return
        payload: dict[str, Any] = {"event": "voice2." + ev.kind}
        if ev.text is not None:
            payload["text"] = ev.text
        if ev.data is not None:
            payload["data"] = ev.data
        # Telnyx ignores unknown events. We send anyway for visibility.
        await ws.send_text(json.dumps(payload))
        event_bus.publish(call_id, {"type": ev.kind, **(payload if ev.text else {})})
        if ev.kind == "agent_text" and ev.text:
            transcript_log.append({"role": "assistant", "text": ev.text})
    except Exception as exc:
        log.warning("telnyx.emit.err", err=str(exc))


async def _finalise(db: AsyncSession, call: Call, transcript: list[dict]) -> None:
    now = datetime.now(UTC)
    call.status = CallStatus.completed
    call.ended_at = now
    if call.started_at:
        call.duration_ms = int((now - call.started_at).total_seconds() * 1000)
    call.transcript = transcript or call.transcript
    db.add(CallEvent(call_id=call.id, at=now, kind="telnyx.media.closed", payload={"turns": len(transcript)}))
    await db.commit()
