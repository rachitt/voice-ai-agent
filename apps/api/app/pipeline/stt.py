"""Deepgram Nova-3 streaming STT client.

Async producer: caller pushes PCM frames; iterator yields TranscriptEvents.
PCM expected as signed 16-bit LE mono at agreed sample rate (default 16000).
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

import websockets

from app.core.config import get_settings
from app.core.logging import log

DG_URL = "wss://api.deepgram.com/v1/listen"


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool
    speech_final: bool
    confidence: float
    type: Literal["transcript", "vad", "error", "close"] = "transcript"
    raw: dict | None = None


class DeepgramStream:
    def __init__(
        self,
        *,
        model: str = "nova-3",
        language: str = "en",
        sample_rate: int = 16000,
        smart_format: bool = True,
        interim_results: bool = True,
        endpointing_ms: int = 300,
        vad_events: bool = True,
        redact: list[str] | None = None,
    ) -> None:
        self.model = model
        self.language = language
        self.sample_rate = sample_rate
        self.smart_format = smart_format
        self.interim_results = interim_results
        self.endpointing_ms = endpointing_ms
        self.vad_events = vad_events
        self.redact = redact or []

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._send_q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self._closed = asyncio.Event()

    def _query(self) -> str:
        params = {
            "model": self.model,
            "language": self.language,
            "encoding": "linear16",
            "sample_rate": self.sample_rate,
            "channels": 1,
            "smart_format": "true" if self.smart_format else "false",
            "interim_results": "true" if self.interim_results else "false",
            "endpointing": self.endpointing_ms,
            "vad_events": "true" if self.vad_events else "false",
        }
        for _r in self.redact:
            params.setdefault("redact", []) if isinstance(params.get("redact"), list) else None
        # Deepgram allows repeated redact=foo&redact=bar params; build manually below.
        base = urlencode({k: v for k, v in params.items() if k != "redact"})
        for r in self.redact:
            base += f"&redact={r}"
        return base

    async def __aenter__(self) -> DeepgramStream:
        key = get_settings().deepgram_api_key
        if not key:
            raise RuntimeError("DEEPGRAM_API_KEY not configured")
        url = f"{DG_URL}?{self._query()}"
        self._ws = await websockets.connect(
            url, additional_headers={"Authorization": f"Token {key}"}
        )
        asyncio.create_task(self._sender())
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _sender(self) -> None:
        assert self._ws is not None
        try:
            while True:
                frame = await self._send_q.get()
                if frame is None:
                    await self._ws.send(json.dumps({"type": "CloseStream"}))
                    return
                await self._ws.send(frame)
        except Exception as exc:
            log.warning("stt.sender.error", err=str(exc))

    async def push(self, pcm_frame: bytes) -> None:
        await self._send_q.put(pcm_frame)

    async def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        await self._send_q.put(None)
        if self._ws is not None:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=2.0)
            except Exception:
                pass

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        assert self._ws is not None
        async for raw in self._ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "SpeechStarted":
                yield TranscriptEvent(text="", is_final=False, speech_final=False, confidence=0, type="vad", raw=msg)
                continue
            if mtype == "UtteranceEnd":
                yield TranscriptEvent(text="", is_final=True, speech_final=True, confidence=1.0, type="vad", raw=msg)
                continue

            alt = (((msg.get("channel") or {}).get("alternatives") or [{}])[0])
            text = alt.get("transcript", "")
            if not text and not msg.get("is_final"):
                continue
            yield TranscriptEvent(
                text=text,
                is_final=bool(msg.get("is_final")),
                speech_final=bool(msg.get("speech_final")),
                confidence=float(alt.get("confidence", 0.0)),
                raw=msg,
            )
