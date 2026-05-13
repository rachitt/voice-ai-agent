"""Voice pipeline orchestrator.

Owns a single live conversation: STT events in, LLM-streamed reply out, TTS
audio out, tool calls dispatched mid-turn. Designed for text-mode unit tests
by injecting fake LLM/TTS providers.

Wire-up at call-time:

    pipe = Pipeline(cfg, llm=litellm_turn, tts=elevenlabs_tts, tool_dispatch=...)
    await pipe.start()
    async for ev in pipe.events():
        ...
    await pipe.feed_user_text("hello", is_final=True)
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import log
from app.pipeline import llm as llm_mod

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AgentConfig:
    model_id: str = "gemini/gemini-3.1-flash-lite"
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    system_prompt: str = ""
    first_message: str | None = None
    tools: list[dict] = field(default_factory=list)  # OpenAI tool schemas
    temperature: float = 0.3
    sample_rate: int = 16000
    knowledge_base_ids: list[str] = field(default_factory=list)
    embedding_model: str = "text-embedding-3-small"
    flow_graph: dict | None = None


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TextChunk:
    text: str


@dataclass
class TurnComplete:
    finish_reason: str = "stop"
    tool_calls: list[ToolCall] = field(default_factory=list)


LLMEvent = TextChunk | ToolCall | TurnComplete


@dataclass
class PipelineEvent:
    kind: (
        str  # user_text, agent_text, agent_audio, tool_call, tool_result,
        #     turn_end, error, started, flow_node
    )
    text: str | None = None
    is_final: bool = False
    audio: bytes | None = None
    data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Provider protocols (duck-typed via Callable)
# ---------------------------------------------------------------------------

LLMTurn = Callable[..., AsyncIterator[LLMEvent]]
"""Callable: (messages, tools, model_id, temperature) -> AsyncIterator[LLMEvent]"""

TTSFn = Callable[[str], AsyncIterator[bytes]]
"""Callable: (text) -> AsyncIterator[PCM bytes]"""

ToolDispatchFn = Callable[[ToolCall], Awaitable[dict[str, Any]]]
"""Callable: (ToolCall) -> dict result. May mutate underlying call row."""


# ---------------------------------------------------------------------------
# Default litellm-backed LLM turn
# ---------------------------------------------------------------------------


async def litellm_turn(
    *,
    messages: list[dict],
    tools: list[dict] | None,
    model_id: str,
    temperature: float = 0.3,
) -> AsyncIterator[LLMEvent]:
    """Stream a single LLM turn via litellm. Accumulates tool_call deltas."""
    import litellm

    kw: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if tools:
        kw["tools"] = tools
    if model_id.startswith("gemini"):
        from app.core.config import get_settings

        kw["api_key"] = get_settings().gemini_api_key

    tc_buf: dict[int, dict[str, Any]] = {}
    finish_reason = "stop"

    async for chunk in await litellm.acompletion(**kw):
        choices = getattr(chunk, "choices", None) or chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None) or choice.get("delta") or {}
        content = (
            getattr(delta, "content", None) if hasattr(delta, "content") else delta.get("content")
        )
        if content:
            yield TextChunk(text=content)

        deltas_tc = (
            getattr(delta, "tool_calls", None)
            if hasattr(delta, "tool_calls")
            else delta.get("tool_calls")
        )
        if deltas_tc:
            for tcd in deltas_tc:
                idx = getattr(tcd, "index", None)
                if idx is None and isinstance(tcd, dict):
                    idx = tcd.get("index", 0)
                idx = idx if idx is not None else 0
                slot = tc_buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                tcd_id = getattr(tcd, "id", None) or (
                    tcd.get("id") if isinstance(tcd, dict) else None
                )
                if tcd_id:
                    slot["id"] = tcd_id
                fn = getattr(tcd, "function", None) or (
                    tcd.get("function") if isinstance(tcd, dict) else None
                )
                if fn is not None:
                    fname = getattr(fn, "name", None) or (
                        fn.get("name") if isinstance(fn, dict) else None
                    )
                    fargs = getattr(fn, "arguments", None) or (
                        fn.get("arguments") if isinstance(fn, dict) else None
                    )
                    if fname:
                        slot["name"] = fname
                    if fargs:
                        slot["args"] += fargs

        fr = (
            getattr(choice, "finish_reason", None)
            if hasattr(choice, "finish_reason")
            else choice.get("finish_reason")
        )
        if fr:
            finish_reason = fr

    tool_calls: list[ToolCall] = []
    if tc_buf:
        import json as _json

        for slot in tc_buf.values():
            try:
                args = _json.loads(slot["args"]) if slot["args"] else {}
            except Exception:
                args = {"_raw": slot["args"]}
            tool_calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{len(tool_calls)}", name=slot["name"], arguments=args
                )
            )

    yield TurnComplete(finish_reason=finish_reason, tool_calls=tool_calls)


# ---------------------------------------------------------------------------
# Default ElevenLabs TTS one-shot
# ---------------------------------------------------------------------------


async def elevenlabs_tts(
    text: str, *, voice_id: str, sample_rate: int = 16000
) -> AsyncIterator[bytes]:
    """One-shot TTS for a sentence chunk. Use Pipeline._tts_stream for streaming."""
    from app.pipeline.tts import ElevenLabsStream

    async with ElevenLabsStream(voice_id=voice_id, sample_rate=sample_rate) as tts:
        await tts.push_text(text)
        await tts.flush()
        async for frame in tts.audio():
            yield frame


# ---------------------------------------------------------------------------
# Sentence splitter
# ---------------------------------------------------------------------------

_SENT_END = re.compile(r"([.!?])(\s|$)|([:;])(\s)")


def split_for_tts(buf: str, *, min_chars: int = 8) -> tuple[list[str], str]:
    """Split `buf` at sentence ends; keep last partial as remainder."""
    out: list[str] = []
    i = 0
    while True:
        m = _SENT_END.search(buf, i)
        if not m:
            break
        end = m.end()
        chunk = buf[:end].strip()
        if len(chunk) >= min_chars:
            out.append(chunk)
            buf = buf[end:]
            i = 0
        else:
            i = end
    return out, buf


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class Pipeline:
    def __init__(
        self,
        cfg: AgentConfig,
        *,
        llm: LLMTurn | None = None,
        tts: TTSFn | None = None,
        tool_dispatch: ToolDispatchFn | None = None,
    ) -> None:
        self.cfg = cfg
        self._llm = llm or self._default_llm
        self._tts = tts or self._default_tts
        self._dispatch = tool_dispatch
        self._messages: list[dict] = []
        if cfg.system_prompt:
            self._messages.append({"role": "system", "content": cfg.system_prompt})
        self._out: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        self._turn_task: asyncio.Task | None = None
        self._closed = False
        self._user_buf = ""
        # Optional callback invoked after each turn_end event is emitted.
        # FlowExecutor wires itself here to advance the graph.
        self.on_turn_end: Callable[[], Awaitable[None]] | None = None
        # Marker for the per-step system note so FlowExecutor can replace it
        # without leaking earlier step intent into later turns.
        self._STEP_MARKER = "__flow_step__"

    async def _default_llm(self, **kw):
        async for e in litellm_turn(
            model_id=self.cfg.model_id, temperature=self.cfg.temperature, **kw
        ):
            yield e

    async def _default_tts(self, text: str):
        async for frame in elevenlabs_tts(
            text, voice_id=self.cfg.voice_id, sample_rate=self.cfg.sample_rate
        ):
            yield frame

    # --- public API ---------------------------------------------------------

    async def start(self) -> None:
        await self._out.put(PipelineEvent(kind="started"))
        if self.cfg.first_message:
            self._messages.append({"role": "assistant", "content": self.cfg.first_message})
            await self._speak(self.cfg.first_message, also_as_event=True)

    async def feed_user_text(self, text: str, *, is_final: bool = True) -> None:
        """Inject a user transcript (text-mode or post-STT)."""
        if self._closed:
            return
        if not is_final:
            await self._out.put(PipelineEvent(kind="user_text", text=text, is_final=False))
            return
        # Final utterance: cancel any in-flight agent turn (barge-in)
        await self.cancel_current_turn()
        self._messages.append({"role": "user", "content": text})
        await self._out.put(PipelineEvent(kind="user_text", text=text, is_final=True))
        self._turn_task = asyncio.create_task(self._run_turn())

    async def cancel_current_turn(self) -> None:
        t = self._turn_task
        if t and not t.done():
            # Don't try to await ourselves — the on_turn_end callback runs on
            # the turn task; a self-await would deadlock.
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if t is current:
                t.cancel()
            else:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self._turn_task = None

    async def events(self) -> AsyncIterator[PipelineEvent]:
        while True:
            ev = await self._out.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        """Idempotent shutdown. Safe to call from inside the active turn task
        (e.g. via an `on_turn_end` callback): the self-cancel path skips the
        await on the calling task to avoid a deadlock."""
        if self._closed:
            return
        self._closed = True
        await self.cancel_current_turn()
        await self._out.put(None)

    # --- flow-executor hooks ------------------------------------------------

    def set_step_prompt(self, text: str | None) -> None:
        """Replace the active per-step system note (FlowExecutor)."""
        self._messages = [
            m
            for m in self._messages
            if not (
                m.get("role") == "system"
                and isinstance(m.get("content"), str)
                and m["content"].startswith(self._STEP_MARKER)
            )
        ]
        if text:
            self._messages.append({"role": "system", "content": f"{self._STEP_MARKER}{text}"})

    def append_system_note(self, text: str) -> None:
        """Inject a plain system message (e.g. KB results) for the next turn."""
        if text:
            self._messages.append({"role": "system", "content": text})

    def emit_event(self, kind: str, **fields: Any) -> None:
        """Push a custom event onto the outbound stream.

        Used by FlowExecutor to surface graph-execution state (e.g. which
        flow node just became active) to WS consumers without coupling the
        executor to the transport layer.
        """
        self._out.put_nowait(PipelineEvent(kind=kind, **fields))

    def message_count(self) -> int:
        """Test/debug accessor for the underlying message buffer length."""
        return len(self._messages)

    # --- internals ----------------------------------------------------------

    async def _run_turn(self) -> None:
        try:
            await self._llm_to_tts_once()
        except asyncio.CancelledError:
            log.info("pipeline.turn.cancelled")
            raise
        except Exception as exc:
            log.exception("pipeline.turn.error", err=str(exc))
            await self._out.put(PipelineEvent(kind="error", data={"err": str(exc)}))

    async def _llm_to_tts_once(self) -> None:
        # Run LLM turns in a loop; if tool_calls appear, dispatch and continue.
        loop_guard = 0
        while True:
            loop_guard += 1
            if loop_guard > 6:
                log.warning("pipeline.toolloop.guard_hit")
                break

            text_buf = ""
            agent_text_accum = ""
            tool_calls: list[ToolCall] = []
            async for ev in self._llm(messages=list(self._messages), tools=self.cfg.tools or None):
                if isinstance(ev, TextChunk):
                    text_buf += ev.text
                    agent_text_accum += ev.text
                    chunks, text_buf = split_for_tts(text_buf)
                    for c in chunks:
                        await self._speak(c, also_as_event=True)
                elif isinstance(ev, ToolCall):
                    tool_calls.append(ev)  # may also arrive on TurnComplete
                elif isinstance(ev, TurnComplete):
                    tool_calls = ev.tool_calls or tool_calls
                    if text_buf.strip():
                        await self._speak(text_buf.strip(), also_as_event=True)
                        text_buf = ""

            if agent_text_accum:
                self._messages.append({"role": "assistant", "content": agent_text_accum})

            if not tool_calls:
                await self._out.put(PipelineEvent(kind="turn_end"))
                if self.on_turn_end is not None:
                    try:
                        await self.on_turn_end()
                    except Exception as exc:
                        log.exception("pipeline.on_turn_end.err", err=str(exc))
                return

            # Append assistant tool_calls record + tool results, then loop.
            self._messages.append(
                {
                    "role": "assistant",
                    "content": agent_text_accum or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": _safe_json(tc.arguments)},
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                await self._out.put(
                    PipelineEvent(
                        kind="tool_call", text=tc.name, data={"id": tc.id, "args": tc.arguments}
                    )
                )
                result: dict[str, Any] = {"ok": True}
                if self._dispatch:
                    try:
                        result = await self._dispatch(tc)
                    except Exception as exc:
                        log.exception("pipeline.tool.error", name=tc.name, err=str(exc))
                        result = {"error": "tool_failed", "detail": str(exc)}
                await self._out.put(
                    PipelineEvent(
                        kind="tool_result", text=tc.name, data={"id": tc.id, "result": result}
                    )
                )
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": _safe_json(result),
                    }
                )

    async def _speak(self, text: str, *, also_as_event: bool) -> None:
        from app.pipeline import tts_cache
        from app.pipeline.tts import TtsProviderError

        if also_as_event:
            await self._out.put(PipelineEvent(kind="agent_text", text=text, is_final=True))

        # Opportunistic TTS cache — see app/pipeline/tts_cache.py. Big wins
        # for first_message + flow-node prompts, both of which repeat across
        # calls. Default TTS model is `eleven_flash_v2_5` and we always speak
        # at 16 kHz mono LE16, so those are the cache-key dimensions.
        TTS_MODEL = "eleven_flash_v2_5"
        SAMPLE_RATE = 16000
        FRAME_BYTES = 1280  # ~40ms @ 16 kHz mono LE16; keeps the WS cadence sane
        cached = await tts_cache.get_pcm(
            voice_id=self.cfg.voice_id,
            tts_model_id=TTS_MODEL,
            sample_rate=SAMPLE_RATE,
            text=text,
        )
        if cached:
            for i in range(0, len(cached), FRAME_BYTES):
                await self._out.put(
                    PipelineEvent(kind="agent_audio", audio=cached[i : i + FRAME_BYTES])
                )
            return

        accumulated = bytearray()
        try:
            async for frame in self._tts(text):
                accumulated.extend(frame)
                await self._out.put(PipelineEvent(kind="agent_audio", audio=frame))
        except asyncio.CancelledError:
            raise
        except TtsProviderError as exc:
            # Dedicated kind so the UI can render a specific banner ("TTS
            # provider quota exceeded — agent text only") rather than a
            # generic error toast that gets lost.
            log.warning("pipeline.tts.provider_error", err=str(exc))
            await self._out.put(
                PipelineEvent(kind="tts_error", data={"err": str(exc)})
            )
        except Exception as exc:
            log.exception("pipeline.tts.error", err=str(exc))
            await self._out.put(PipelineEvent(kind="error", data={"err": f"tts:{exc}"}))
            return
        # Cache only on full successful synthesis. Partial captures (cancelled
        # mid-utterance, provider error) are skipped so we don't burn a key
        # on a truncated waveform.
        await tts_cache.put_pcm(
            voice_id=self.cfg.voice_id,
            tts_model_id=TTS_MODEL,
            sample_rate=SAMPLE_RATE,
            text=text,
            pcm=bytes(accumulated),
        )


def _safe_json(obj: Any) -> str:
    import json as _json

    if isinstance(obj, str):
        return obj
    try:
        return _json.dumps(obj)
    except Exception:
        return _json.dumps({"_repr": repr(obj)})


# Re-exports for callers that want raw types
__all__ = [
    "AgentConfig",
    "Pipeline",
    "PipelineEvent",
    "TextChunk",
    "ToolCall",
    "TurnComplete",
    "litellm_turn",
    "elevenlabs_tts",
    "split_for_tts",
    "llm_mod",
]
