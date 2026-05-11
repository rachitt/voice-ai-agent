"""Text-mode unit tests for the voice pipeline orchestrator.

Inject fake LLM/TTS so no external API calls happen.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.pipeline.orchestrator import (
    AgentConfig,
    Pipeline,
    PipelineEvent,
    TextChunk,
    ToolCall,
    TurnComplete,
    split_for_tts,
)

# ---------- helpers ---------------------------------------------------------

def make_text_llm(text: str, chunk_size: int = 6):
    async def _turn(*, messages, tools):
        for i in range(0, len(text), chunk_size):
            yield TextChunk(text=text[i : i + chunk_size])
        yield TurnComplete(finish_reason="stop")
    return _turn


def make_tool_then_text_llm(tool_name: str, tool_args: dict, follow_up: str):
    state = {"phase": 0}

    async def _turn(*, messages, tools):
        if state["phase"] == 0:
            state["phase"] = 1
            yield ToolCall(id="tc_1", name=tool_name, arguments=tool_args)
            yield TurnComplete(finish_reason="tool_calls", tool_calls=[
                ToolCall(id="tc_1", name=tool_name, arguments=tool_args)
            ])
            return
        for ch in follow_up.split():
            yield TextChunk(text=ch + " ")
        yield TurnComplete(finish_reason="stop")
    return _turn


def make_fake_tts():
    async def _tts(text: str) -> AsyncIterator[bytes]:
        # 1 byte per char to simulate audio frames; verifies wiring
        for ch in text:
            yield ch.encode("utf-8")
    return _tts


async def collect(p: Pipeline, until_kind: str = "turn_end", timeout: float = 2.0) -> list[PipelineEvent]:
    out: list[PipelineEvent] = []

    async def _drain() -> None:
        async for ev in p.events():
            out.append(ev)
            if ev.kind == until_kind:
                return

    await asyncio.wait_for(_drain(), timeout=timeout)
    return out


# ---------- split_for_tts --------------------------------------------------

def test_split_for_tts_basic():
    chunks, rem = split_for_tts("Hello world. How are you today? I am fine")
    assert chunks == ["Hello world.", "How are you today?"]
    assert rem.strip() == "I am fine"


def test_split_for_tts_short_no_split():
    chunks, rem = split_for_tts("Hi.")
    # Below min_chars threshold, kept in remainder
    assert chunks == []
    assert rem == "Hi."


def test_split_for_tts_colon_break():
    chunks, rem = split_for_tts("Sure, here's what I'll do: call your friend.")
    assert any(c.endswith(":") for c in chunks) or any(c.endswith(".") for c in chunks)


# ---------- pipeline ------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_first_message_then_user_turn():
    cfg = AgentConfig(
        first_message="Hi there. How can I help today?",
        system_prompt="be helpful",
    )
    p = Pipeline(cfg, llm=make_text_llm("All set. Goodbye."), tts=make_fake_tts())
    await p.start()
    await p.feed_user_text("end the call please")

    events = await collect(p, until_kind="turn_end")
    kinds = [e.kind for e in events]
    # started, agent_text(s)+audio for first_message, user_text, agent_text(s)+audio, turn_end
    assert kinds[0] == "started"
    assert "user_text" in kinds
    assert "agent_text" in kinds
    assert "agent_audio" in kinds
    assert kinds[-1] == "turn_end"

    # First message audio bytes should equal the message contents
    first_audio = b"".join(e.audio for e in events if e.audio)
    assert b"Hi there." in first_audio
    await p.close()


@pytest.mark.asyncio
async def test_pipeline_tool_dispatch_loop():
    cfg = AgentConfig(system_prompt="x", tools=[{"type": "function", "function": {"name": "noop", "parameters": {}}}])

    dispatched: list[ToolCall] = []

    async def fake_dispatch(tc: ToolCall) -> dict:
        dispatched.append(tc)
        return {"ok": True, "echo": tc.arguments}

    p = Pipeline(
        cfg,
        llm=make_tool_then_text_llm("noop", {"x": 1}, "Done with the task."),
        tts=make_fake_tts(),
        tool_dispatch=fake_dispatch,
    )
    await p.start()
    await p.feed_user_text("do the thing")
    events = await collect(p, until_kind="turn_end", timeout=3.0)

    kinds = [e.kind for e in events]
    assert kinds.count("tool_call") == 1
    assert kinds.count("tool_result") == 1
    assert dispatched[0].name == "noop"
    assert dispatched[0].arguments == {"x": 1}
    # Final agent text should appear after tool resolution
    agent_texts = [e.text for e in events if e.kind == "agent_text"]
    assert any("Done" in (t or "") for t in agent_texts)
    await p.close()


@pytest.mark.asyncio
async def test_pipeline_barge_in_cancels_previous_turn():
    # LLM that emits one chunk then sleeps "forever" — we expect cancellation
    async def slow_llm(*, messages, tools):
        yield TextChunk(text="I am thinking ")
        await asyncio.sleep(5.0)  # would block; must be cancelled
        yield TurnComplete(finish_reason="stop")

    p = Pipeline(AgentConfig(), llm=slow_llm, tts=make_fake_tts())
    await p.start()
    await p.feed_user_text("first question")
    await asyncio.sleep(0.05)
    # Barge-in: new user utterance must cancel previous turn
    p2_llm = make_text_llm("Quick reply.")
    p._llm = p2_llm  # type: ignore[assignment]
    await p.feed_user_text("never mind, different question")

    events = await collect(p, until_kind="turn_end", timeout=2.0)
    assert any(e.kind == "agent_text" and (e.text or "").startswith("Quick") for e in events)
    await p.close()


@pytest.mark.asyncio
async def test_pipeline_appends_assistant_history():
    p = Pipeline(AgentConfig(system_prompt="sys"), llm=make_text_llm("Reply A."), tts=make_fake_tts())
    await p.start()
    await p.feed_user_text("hi")
    await collect(p, until_kind="turn_end")

    roles = [m["role"] for m in p._messages]  # noqa: SLF001 — test introspection
    assert roles[0] == "system"
    assert "user" in roles
    assert "assistant" in roles
    await p.close()
