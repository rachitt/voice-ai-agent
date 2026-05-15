"""Pipeline emits per-call TTS cache hit/miss counters.

We measure savings by character count: every cache hit avoids `miss_chars`
worth of ElevenLabs spend. Stats are stashed on `call.dynamic_variables`
at finalisation so analytics can roll them up without a schema change.
"""

from __future__ import annotations

import pytest

from app.pipeline import tts_cache
from app.pipeline.orchestrator import AgentConfig, Pipeline


async def _fake_tts(text: str):
    """8 ms / char of fake PCM so we exercise the per-char counter cleanly."""
    yield b"\x00\x00" * 16  # 32 bytes per call; size doesn't matter for stats


@pytest.fixture(autouse=True)
def _stub_cache(monkeypatch):
    """In-memory cache that the orchestrator drives through tts_cache."""
    store: dict[str, bytes] = {}

    async def fake_get_pcm(*, voice_id, tts_model_id, sample_rate, text):
        key = f"{voice_id}|{tts_model_id}|{sample_rate}|{text}"
        return store.get(key)

    async def fake_put_pcm(*, voice_id, tts_model_id, sample_rate, text, pcm):
        key = f"{voice_id}|{tts_model_id}|{sample_rate}|{text}"
        store[key] = pcm

    monkeypatch.setattr(tts_cache, "get_pcm", fake_get_pcm)
    monkeypatch.setattr(tts_cache, "put_pcm", fake_put_pcm)
    yield store


@pytest.mark.asyncio
async def test_first_speak_is_a_miss(monkeypatch):
    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=_fake_tts)
    await pipe._speak("hello there friend", also_as_event=False)
    stats = pipe.tts_stats
    assert stats == {"hits": 1 * 0 + 0, "misses": 1, "miss_chars": len("hello there friend")}


@pytest.mark.asyncio
async def test_second_identical_speak_is_a_hit(_stub_cache):
    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=_fake_tts)
    await pipe._speak("repeat me please", also_as_event=False)
    await pipe._speak("repeat me please", also_as_event=False)
    stats = pipe.tts_stats
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["miss_chars"] == len("repeat me please")


@pytest.mark.asyncio
async def test_different_voice_does_not_share_cache(_stub_cache):
    cfg_a = AgentConfig(voice_id="va", first_message=None, system_prompt="")
    cfg_b = AgentConfig(voice_id="vb", first_message=None, system_prompt="")
    pa, pb = Pipeline(cfg_a, tts=_fake_tts), Pipeline(cfg_b, tts=_fake_tts)
    await pa._speak("xyz longer than four", also_as_event=False)
    await pb._speak("xyz longer than four", also_as_event=False)
    assert pa.tts_stats["misses"] == 1
    assert pb.tts_stats["misses"] == 1
    assert pa.tts_stats["hits"] == 0
    assert pb.tts_stats["hits"] == 0


@pytest.mark.asyncio
async def test_stats_isolated_per_pipeline(_stub_cache):
    """Two pipelines mustn't share the in-memory counter."""
    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pa, pb = Pipeline(cfg, tts=_fake_tts), Pipeline(cfg, tts=_fake_tts)
    await pa._speak("only on pa one", also_as_event=False)
    assert pa.tts_stats == {"hits": 0, "misses": 1, "miss_chars": len("only on pa one")}
    assert pb.tts_stats == {"hits": 0, "misses": 0, "miss_chars": 0}


@pytest.mark.asyncio
async def test_tts_stats_property_is_a_copy():
    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=_fake_tts)
    snap = pipe.tts_stats
    snap["hits"] = 999
    # Internal state unchanged — read-only snapshot.
    assert pipe.tts_stats["hits"] == 0


# ----- _finalise_call persistence (web_call_ws) -----------------------------


# ----- _speak TTS failure modes ---------------------------------------------


@pytest.mark.asyncio
async def test_speak_emits_tts_error_on_provider_failure(_stub_cache):
    from app.pipeline.tts import TtsProviderError

    async def boom(_text):
        if False:
            yield b""
        raise TtsProviderError("quota_exceeded")

    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=boom)
    await pipe._speak("hello quota gone", also_as_event=True)

    kinds: list[str] = []
    while not pipe._out.empty():
        ev = pipe._out.get_nowait()
        if ev is not None:
            kinds.append(ev.kind)
    assert "tts_error" in kinds
    # Provider error counts as a miss (the synth was attempted).
    assert pipe.tts_stats["misses"] == 1
    assert pipe.tts_stats["hits"] == 0


@pytest.mark.asyncio
async def test_speak_emits_generic_error_on_unexpected_failure(_stub_cache):
    async def boom(_text):
        if False:
            yield b""
        raise RuntimeError("transport boom")

    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=boom)
    await pipe._speak("trigger generic error path", also_as_event=False)

    seen: list = []
    while not pipe._out.empty():
        ev = pipe._out.get_nowait()
        if ev is not None:
            seen.append(ev)
    err = [e for e in seen if e.kind == "error"]
    assert err and err[0].data and "transport boom" in err[0].data["err"]


@pytest.mark.asyncio
async def test_speak_provider_error_does_not_cache_partial(_stub_cache):
    """Cache must NOT be populated when synthesis fails mid-stream."""
    from app.pipeline.tts import TtsProviderError

    async def partial_then_fail(_text):
        yield b"\x00" * 32
        raise TtsProviderError("network reset")

    cfg = AgentConfig(voice_id="v1", first_message=None, system_prompt="")
    pipe = Pipeline(cfg, tts=partial_then_fail)
    await pipe._speak("partial failure text", also_as_event=False)
    # Cache stub is empty.
    assert _stub_cache == {}


@pytest.mark.asyncio
async def test_finalise_call_writes_tts_stats(db_session):
    from datetime import UTC, datetime

    from app.db import models
    from app.routers.web_call_ws import _finalise_call

    org = models.Org(name="TtsOrg", slug="tts-stats")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        direction=models.CallDirection.web,
        status=models.CallStatus.in_progress,
        started_at=datetime.now(UTC),
    )
    db_session.add(call)
    await db_session.commit()

    await _finalise_call(
        db_session,
        call,
        [{"role": "user", "text": "hi"}],
        tts_stats={"hits": 3, "misses": 2, "miss_chars": 40},
    )
    await db_session.refresh(call)
    assert call.dynamic_variables.get("tts_cache") == {
        "hits": 3,
        "misses": 2,
        "miss_chars": 40,
    }
    assert call.status == models.CallStatus.completed
