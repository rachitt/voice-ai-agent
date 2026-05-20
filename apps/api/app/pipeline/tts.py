"""ElevenLabs Flash v2.5 streaming TTS.

Text chunks pushed via push_text(); raw PCM frames yielded over the audio()
async iterator. Format: pcm_16000 (16-bit LE mono at 16 kHz) by default.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator

import websockets

from app.core.config import get_settings
from app.core.logging import log

EL_WS = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"


class ElevenLabsStream:
    def __init__(
        self,
        *,
        voice_id: str,
        model_id: str = "eleven_flash_v2_5",
        sample_rate: int = 16000,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
    ) -> None:
        self.voice_id = voice_id
        self.model_id = model_id
        self.sample_rate = sample_rate
        self.stability = stability
        self.similarity_boost = similarity_boost
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._closed = asyncio.Event()

    async def __aenter__(self) -> ElevenLabsStream:
        key = get_settings().elevenlabs_api_key
        if not key:
            raise RuntimeError("ELEVENLABS_API_KEY not configured")
        url = EL_WS.format(voice_id=self.voice_id) + (
            f"?model_id={self.model_id}&output_format=pcm_{self.sample_rate}&auto_mode=true"
        )
        self._ws = await websockets.connect(url, additional_headers={"xi-api-key": key})
        await self._ws.send(
            json.dumps(
                {
                    "text": " ",
                    "voice_settings": {
                        "stability": self.stability,
                        "similarity_boost": self.similarity_boost,
                    },
                }
            )
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def push_text(self, text: str) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps({"text": text}))

    async def flush(self) -> None:
        if not self._ws:
            return
        await self._ws.send(json.dumps({"text": ""}))

    async def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        if self._ws:
            try:
                await self._ws.send(json.dumps({"text": ""}))
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except Exception:
                pass

    async def audio(self) -> AsyncIterator[bytes]:
        assert self._ws is not None
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("audio"):
                yield base64.b64decode(msg["audio"])
            if msg.get("isFinal"):
                return
            if msg.get("error"):
                # Raise instead of swallowing — the orchestrator's `_speak`
                # catch will emit a pipeline error event the WS forwards to
                # the dashboard. Silent TTS failure was the worst kind of bug:
                # LLM kept generating text, but the user heard nothing.
                log.warning("tts.error", err=msg["error"])
                raise TtsProviderError(str(msg["error"]))


class TtsProviderError(RuntimeError):
    """ElevenLabs returned an error frame (quota_exceeded, voice_not_found, …).

    Surfaced up to `Pipeline._speak` so the WS can tell the UI why the
    agent went silent."""


async def synth_pcm(
    *,
    text: str,
    voice_id: str,
    model_id: str = "eleven_flash_v2_5",
    sample_rate: int = 16000,
) -> bytes:
    """One-shot synthesis: push text → drain audio → return concatenated PCM.

    Used by the test-call panel to mint canned voice clips on demand. Hits
    the same Redis cache the orchestrator's `_speak` uses (`tts_cache`),
    keyed by (voice_id, model_id, sample_rate, text), so repeat synthesis
    of the same line is free after the first call.

    Returns PCM16 LE @ 16 kHz mono by default — the wire format the
    pcm-capture-worklet on the browser side speaks fluently."""
    from app.pipeline import tts_cache

    cached = await tts_cache.get_pcm(
        voice_id=voice_id,
        tts_model_id=model_id,
        sample_rate=sample_rate,
        text=text,
    )
    if cached:
        return cached

    accumulated = bytearray()
    async with ElevenLabsStream(
        voice_id=voice_id,
        model_id=model_id,
        sample_rate=sample_rate,
    ) as tts:
        await tts.push_text(text)
        await tts.flush()
        async for frame in tts.audio():
            accumulated.extend(frame)

    pcm = bytes(accumulated)
    await tts_cache.put_pcm(
        voice_id=voice_id,
        tts_model_id=model_id,
        sample_rate=sample_rate,
        text=text,
        pcm=pcm,
    )
    return pcm
