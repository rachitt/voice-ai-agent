"""ElevenLabsStream: connect (mocked WS), push/flush/close, audio iterator."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.pipeline import tts as tts_mod


class FakeWS:
    """Minimal WS double — captures sends, lets tests script incoming messages."""

    def __init__(self, incoming: list[str] | None = None) -> None:
        self.sent: list[str] = []
        self.incoming: list[str] = incoming or []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[str]:
        for msg in self.incoming:
            yield msg


@pytest.mark.asyncio
async def test_connect_requires_api_key(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.delenv("VOICE_ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "")  # explicit blank
    s = tts_mod.ElevenLabsStream(voice_id="v1")
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        await s.__aenter__()
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_connect_sends_handshake(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "test-key")

    captured: dict[str, Any] = {}
    fake = FakeWS()

    async def fake_connect(url: str, additional_headers: dict | None = None):
        captured["url"] = url
        captured["headers"] = additional_headers
        return fake

    monkeypatch.setattr(tts_mod.websockets, "connect", fake_connect)
    s = tts_mod.ElevenLabsStream(voice_id="voice_abc", sample_rate=24000)
    async with s:
        assert "voice_abc" in captured["url"]
        assert "pcm_24000" in captured["url"]
        assert captured["headers"] == {"xi-api-key": "test-key"}
        # First send is the handshake with voice_settings.
        first = json.loads(fake.sent[0])
        assert first["text"] == " "
        assert "voice_settings" in first
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_push_text_flush_send_payloads(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "k")
    fake = FakeWS()

    async def fake_connect(url, additional_headers=None):
        return fake

    monkeypatch.setattr(tts_mod.websockets, "connect", fake_connect)
    s = tts_mod.ElevenLabsStream(voice_id="v")
    async with s:
        await s.push_text("hello world")
        await s.flush()
    # 1 handshake + push + flush + close-flush
    payloads = [json.loads(x) for x in fake.sent]
    assert any(p == {"text": "hello world"} for p in payloads)
    assert any(p == {"text": ""} for p in payloads)
    assert fake.closed is True
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_push_and_flush_noop_when_not_connected():
    s = tts_mod.ElevenLabsStream(voice_id="v")
    # No connect; ensure these are safe no-ops (do not raise).
    await s.push_text("hi")
    await s.flush()
    await s.close()
    # Re-close idempotent.
    await s.close()


@pytest.mark.asyncio
async def test_audio_iterator_yields_decoded_and_stops_on_final(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "k")
    pcm = b"\x01\x02\x03\x04"
    msgs = [
        json.dumps({"audio": base64.b64encode(pcm).decode()}),
        "not-json-line",  # decode error path
        json.dumps({"audio": base64.b64encode(pcm).decode()}),
        json.dumps({"isFinal": True}),
        json.dumps({"audio": base64.b64encode(b"after-final").decode()}),  # should not yield
    ]
    fake = FakeWS(incoming=msgs)

    async def fake_connect(url, additional_headers=None):
        return fake

    monkeypatch.setattr(tts_mod.websockets, "connect", fake_connect)
    s = tts_mod.ElevenLabsStream(voice_id="v")
    async with s:
        out: list[bytes] = []
        async for chunk in s.audio():
            out.append(chunk)
        assert out == [pcm, pcm]
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_audio_iterator_stops_on_error(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "k")
    msgs = [
        json.dumps({"error": "quota exceeded"}),
        json.dumps({"audio": base64.b64encode(b"after-error").decode()}),
    ]
    fake = FakeWS(incoming=msgs)

    async def fake_connect(url, additional_headers=None):
        return fake

    monkeypatch.setattr(tts_mod.websockets, "connect", fake_connect)
    s = tts_mod.ElevenLabsStream(voice_id="v")
    async with s:
        out: list[bytes] = []
        # Provider error must raise so the orchestrator can surface a banner
        # in the UI — silent return used to mean the agent went mute without
        # any signal.
        import pytest as _pytest

        with _pytest.raises(tts_mod.TtsProviderError):
            async for chunk in s.audio():
                out.append(chunk)
        assert out == []
    cfg.get_settings.cache_clear()
