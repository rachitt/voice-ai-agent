"""DeepgramStream: connect, query string, sender, events parsing."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.pipeline import stt as stt_mod


class FakeWS:
    def __init__(self, incoming: list[str] | None = None) -> None:
        self.sent: list[Any] = []
        self.incoming = incoming or []
        self.closed = False

    async def send(self, data: Any) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for m in self.incoming:
            yield m


def test_query_builds_params_and_repeats_redact():
    s = stt_mod.DeepgramStream(
        model="nova-3", language="es", sample_rate=8000, redact=["pci", "ssn"]
    )
    q = s._query()
    assert "model=nova-3" in q
    assert "language=es" in q
    assert "sample_rate=8000" in q
    assert "encoding=linear16" in q
    assert "redact=pci" in q
    assert "redact=ssn" in q


def test_query_flags_false_when_disabled():
    s = stt_mod.DeepgramStream(smart_format=False, interim_results=False, vad_events=False)
    q = s._query()
    assert "smart_format=false" in q
    assert "interim_results=false" in q
    assert "vad_events=false" in q


@pytest.mark.asyncio
async def test_connect_requires_api_key(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_DEEPGRAM_API_KEY", "")
    s = stt_mod.DeepgramStream()
    with pytest.raises(RuntimeError, match="DEEPGRAM_API_KEY"):
        await s.__aenter__()
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_connect_sends_auth_header(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_DEEPGRAM_API_KEY", "dg-test")
    captured: dict[str, Any] = {}
    fake = FakeWS()

    async def fake_connect(url, additional_headers=None):
        captured.update(url=url, headers=additional_headers)
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)
    s = stt_mod.DeepgramStream()
    async with s:
        assert captured["headers"] == {"Authorization": "Token dg-test"}
        assert "model=nova-3" in captured["url"]
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_push_then_close_drains_queue(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_DEEPGRAM_API_KEY", "k")
    fake = FakeWS()

    async def fake_connect(url, additional_headers=None):
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)
    s = stt_mod.DeepgramStream()
    async with s:
        await s.push(b"frame-1")
        await s.push(b"frame-2")
        # Give the sender task a moment to drain.
        for _ in range(20):
            if b"frame-1" in fake.sent and b"frame-2" in fake.sent:
                break
            await asyncio.sleep(0.005)
    # close sends a CloseStream JSON message via the sender.
    assert b"frame-1" in fake.sent
    assert b"frame-2" in fake.sent
    json_msgs = [m for m in fake.sent if isinstance(m, str)]
    assert any(json.loads(m) == {"type": "CloseStream"} for m in json_msgs)
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_close_is_idempotent():
    s = stt_mod.DeepgramStream()
    await s.close()
    await s.close()


@pytest.mark.asyncio
async def test_events_emits_vad_and_transcripts(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_DEEPGRAM_API_KEY", "k")
    msgs = [
        "garbage-not-json",  # decode error path
        json.dumps({"type": "SpeechStarted"}),
        json.dumps(
            {
                "type": "Results",
                "channel": {
                    "alternatives": [{"transcript": "hello world", "confidence": 0.92}]
                },
                "is_final": True,
                "speech_final": False,
            }
        ),
        # Empty interim with no is_final → skipped
        json.dumps({"channel": {"alternatives": [{"transcript": ""}]}, "is_final": False}),
        # Empty transcript with is_final=true is still yielded
        json.dumps({"channel": {"alternatives": [{"transcript": ""}]}, "is_final": True}),
        json.dumps({"type": "UtteranceEnd"}),
    ]
    fake = FakeWS(incoming=msgs)

    async def fake_connect(url, additional_headers=None):
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)
    s = stt_mod.DeepgramStream()
    async with s:
        out = [ev async for ev in s.events()]

    assert [e.type for e in out] == ["vad", "transcript", "transcript", "vad"]
    assert out[0].type == "vad" and out[0].speech_final is False
    assert out[1].text == "hello world"
    assert out[1].is_final is True
    assert out[1].confidence == pytest.approx(0.92)
    assert out[-1].type == "vad" and out[-1].speech_final is True
    cfg.get_settings.cache_clear()
