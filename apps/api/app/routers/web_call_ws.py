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

import httpx
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.scheduler import schedule_post_call
from app.core.config import get_settings
from app.core.logging import log
from app.db.models import AgentVersion, Call, CallEvent, CallStatus, Tool
from app.db.session import SessionLocal
from app.pipeline import event_bus
from app.pipeline.flow_executor import FlowExecutor, has_executable_graph
from app.pipeline.orchestrator import AgentConfig, Pipeline, PipelineEvent, ToolCall
from app.pipeline.recording import CallRecorder, recording_key
from app.pipeline.stt import DeepgramStream
from app.pipeline.web_session import verify_ws_token
from app.storage.s3 import put_object_bytes
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
    return (await db.execute(select(Call).where(Call.id == call_id))).scalar_one_or_none()


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
            await db.execute(select(AgentVersion).where(AgentVersion.id == call.agent_version_id))
        ).scalar_one_or_none()
    if ver is None:
        return None

    tool_defs, custom_tools = await _resolve_tools(ver, db=db, org_id=call.org_id)

    cfg = AgentConfig(
        model_id=ver.model_id,
        voice_id=ver.voice_id,
        system_prompt=ver.system_prompt or "",
        first_message=ver.first_message,
        tools=tool_defs,
        knowledge_base_ids=list(ver.knowledge_base_ids or []),
        flow_graph=ver.flow_graph if isinstance(ver.flow_graph, dict) else None,
    )
    # Stash the resolved custom tools on the AgentConfig so `_run_session`
    # can dispatch them without re-querying. AgentConfig itself stays
    # transport-agnostic; this attribute is a private side-channel.
    cfg._custom_tools = custom_tools  # type: ignore[attr-defined]
    return cfg


async def _resolve_tools(
    ver: AgentVersion, *, db: AsyncSession | None = None, org_id: str | None = None
) -> tuple[list[dict], dict[str, Tool]]:
    """Resolve a version's tool refs into:
      1. A list of OpenAI tool schemas the LLM will see (`tools` arg).
      2. A `{name: Tool}` map of *custom* (user-registered, HTTP-dispatched)
         tools so `_run_session` can route calls back to their server_url.

    Tool refs can be:
      - A built-in name like "transfer_call" → schema lifted from REGISTRY.
      - A custom Tool id like "tool_..." → schema synthesised from the row
        (name + description + params_schema).
      - A raw OpenAI tool dict — pass-through (legacy fallback).

    kb_lookup is auto-bound when the agent has bound KBs or its flow graph
    references a kb_lookup node, so editors don't have to remember to add
    it explicitly.
    """
    tool_defs: list[dict] = []
    custom_tools: dict[str, Tool] = {}
    seen: set[str] = set()

    def _add(defn: dict) -> None:
        name = defn.get("function", {}).get("name")
        if name and name not in seen:
            tool_defs.append(defn)
            seen.add(name)

    # Pre-fetch any custom tool ids in one query so we don't N+1.
    ref_strings = [t for t in (ver.tools or []) if isinstance(t, str)]
    ref_strings += [
        t.get("name") for t in (ver.tools or []) if isinstance(t, dict) and "name" in t and isinstance(t.get("name"), str)
    ]
    tool_ids = [s for s in ref_strings if s.startswith("tool_")]
    db_rows: dict[str, Tool] = {}
    if tool_ids and db is not None and org_id is not None:
        rows = (
            await db.execute(
                select(Tool).where(Tool.org_id == org_id, Tool.id.in_(tool_ids))
            )
        ).scalars().all()
        db_rows = {r.id: r for r in rows}

    for t in ver.tools or []:
        if isinstance(t, dict) and t.get("type") == "function":
            _add(t)
            continue
        ref = t.get("name") if isinstance(t, dict) else t if isinstance(t, str) else None
        if not ref:
            continue
        # 1) built-in
        entry = REGISTRY.get(ref)
        if entry:
            _add(entry["definition"])
            continue
        # 2) custom tool row
        row = db_rows.get(ref)
        if row:
            defn = _custom_tool_to_openai(row)
            _add(defn)
            custom_tools[row.name] = row

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

    return tool_defs, custom_tools


async def _dispatch_http_tool(
    row: Tool, args: dict[str, Any], *, call_id: str
) -> dict[str, Any]:
    """POST the LLM-generated `args` to the user-configured tool endpoint
    and return a dict the LLM can use as the tool's result. Errors are
    coerced into a normal result so the LLM can react ("the tool failed,
    please try again") instead of crashing the call."""
    timeout = max(0.5, (row.timeout_ms or 10000) / 1000.0)
    headers = {"content-type": "application/json", **(row.headers or {})}
    # Stamp the active call so user backends can correlate logs.
    headers.setdefault("X-Voice-Call-Id", call_id)
    method = (row.method or "POST").upper()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.request(
                method,
                row.server_url,
                json=args if method != "GET" else None,
                params=args if method == "GET" else None,
                headers=headers,
            )
        body: Any
        try:
            body = r.json()
        except Exception:
            body = (r.text or "")[:2000]
        if not 200 <= r.status_code < 300:
            log.warning(
                "tool.http.bad_status",
                tool=row.name,
                status=r.status_code,
                url=row.server_url,
            )
            return {"error": "http_error", "status": r.status_code, "body": body}
        return {"ok": True, "result": body}
    except httpx.TimeoutException:
        log.warning("tool.http.timeout", tool=row.name, url=row.server_url, timeout_s=timeout)
        return {"error": "timeout", "timeout_s": timeout}
    except Exception as exc:
        log.exception("tool.http.err", tool=row.name, err=str(exc))
        return {"error": "transport_error", "detail": str(exc)}


def _custom_tool_to_openai(row: Tool) -> dict:
    """Translate a DB Tool row into the OpenAI function-tool schema the LLM
    consumes. `params_schema` is trusted to already be a JSON Schema; if it
    isn't an object, fall back to a permissive empty schema so the LLM at
    least sees the tool by name."""
    params = row.params_schema if isinstance(row.params_schema, dict) else {}
    if "type" not in params:
        params = {"type": "object", "properties": params or {}}
    return {
        "type": "function",
        "function": {
            "name": row.name,
            "description": row.description or f"Custom tool: {row.name}",
            "parameters": params,
        },
    }


async def _run_session(
    ws: WebSocket,
    db: AsyncSession,
    call: Call,
    cfg: AgentConfig,
    *,
    text_only: bool,
) -> None:
    custom_tools: dict[str, Tool] = getattr(cfg, "_custom_tools", {}) or {}

    async def tool_dispatch(tc: ToolCall) -> dict[str, Any]:
        # 1. Built-in (transfer_call, kb_lookup, …) — runs in-process.
        entry = REGISTRY.get(tc.name)
        if entry:
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

        # 2. Custom HTTP tool (calendar, CRM, etc.) — POST to server_url
        #    with the LLM-produced arguments. This is the path that makes
        #    a "create_calendar_event" tool actually call your service.
        row = custom_tools.get(tc.name)
        if row:
            return await _dispatch_http_tool(row, tc.arguments, call_id=call.id)

        return {"error": "unknown_tool", "name": tc.name}

    pipe = Pipeline(cfg, tool_dispatch=tool_dispatch)
    recorder = CallRecorder(sample_rate=cfg.sample_rate)

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
                        await ws.send_json(
                            {
                                "type": "stt",
                                "text": ev.text,
                                "is_final": ev.is_final,
                                "speech_final": ev.speech_final,
                            }
                        )
                    if ev.speech_final and buf:
                        await pipe.feed_user_text(buf, is_final=True)
                        transcript_log.append({"role": "user", "text": buf})
                        buf = ""

            stt_pusher_task = asyncio.create_task(_stt_pump())

    async def _drain_pipeline() -> None:
        async for ev in pipe.events():
            if ev.kind == "agent_audio" and ev.audio:
                recorder.push_agent(ev.audio)
            await _emit(ws, ev, transcript_log, call.id)

    drainer = asyncio.create_task(_drain_pipeline())

    async def _kb_call(kb_id: str, query: str, top_k: int = 5) -> dict[str, Any]:
        entry = REGISTRY.get("kb_lookup")
        if not entry:
            return {"error": "kb_lookup_unavailable"}
        ctx = ToolContext(
            call=call,
            db=db,
            telnyx=None,
            args={"kb_id": kb_id, "query": query, "top_k": top_k},
            knowledge_base_ids=list(cfg.knowledge_base_ids or []),
            embedding_model=cfg.embedding_model,
        )
        return await entry["handler"](ctx)

    flow: FlowExecutor | None = None
    if has_executable_graph(cfg.flow_graph):
        # Mutate the call row's dynamic_variables in place so api-node responses
        # persist for downstream nodes (and the post-call analysis).
        if call.dynamic_variables is None:
            call.dynamic_variables = {}
        flow = FlowExecutor(
            graph=cfg.flow_graph or {},
            cfg=cfg,
            pipe=pipe,
            kb_dispatch=_kb_call,
            variables=call.dynamic_variables,
        )

    try:
        if flow is not None:
            await flow.start()
        else:
            await pipe.start()
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"] is not None:
                recorder.push_user(msg["bytes"])
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
        await _upload_recording(call, recorder)
        await _finalise_call(db, call, transcript_log)
        schedule_post_call(call.id)
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


async def _upload_recording(call: Call, recorder: CallRecorder) -> None:
    """Encode the in-memory PCM buffers to WAV and upload to S3. Best-effort:
    if `enable_object_store` is off or upload fails, leaves recording_s3_key
    untouched so the call still finalises."""
    if not get_settings().enable_object_store:
        return
    if not recorder.has_audio():
        return
    try:
        wav_bytes = recorder.finalise()
    except Exception as exc:
        log.warning("ws.recording.encode_err", call=call.id, err=str(exc))
        return
    if not wav_bytes:
        return
    key = recording_key(org_id=call.org_id, call_id=call.id)
    stored = await put_object_bytes(
        bucket=get_settings().s3_bucket_recordings,
        key=key,
        data=wav_bytes,
        content_type="audio/wav",
    )
    if stored:
        call.recording_s3_key = stored


async def _finalise_call(db: AsyncSession, call: Call, transcript: list[dict]) -> None:
    try:
        now = datetime.now(UTC)
        if call.status != CallStatus.completed:
            call.status = CallStatus.completed
        call.ended_at = now
        if call.started_at:
            call.duration_ms = int((now - call.started_at).total_seconds() * 1000)
        call.transcript = transcript or call.transcript
        db.add(
            CallEvent(call_id=call.id, at=now, kind="ws.closed", payload={"turns": len(transcript)})
        )
        await db.commit()
    except Exception as exc:
        log.warning("ws.finalise.error", err=str(exc))
