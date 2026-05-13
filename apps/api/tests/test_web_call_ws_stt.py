"""Cover `_stt_pump` loop branches + `stt_unavailable` warn path in
`web_call_ws`. Existing `test_ws_session_loop.py::FakeDG` yields nothing,
so the pump body never executes; here we drive synthetic
`TranscriptEvent`s through a fake and assert the route emits `stt`
frames + forwards finals to the Pipeline. We also force the STT
constructor to raise so the route hits the warn / send_json branch.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.pipeline.orchestrator import AgentConfig, PipelineEvent
from app.pipeline.stt import TranscriptEvent
from app.pipeline.web_session import mint_ws_token
from app.routers import telnyx_media_ws as tmws
from app.routers import web_call_ws as wcws

from tests.test_ws_session_loop import (
    FakePipeline,
    LoopBoundSessionLocal,
    _read_call_state,
    _seed_call_sync,
)


class FakeDGWithTranscripts:
    """Drop-in DeepgramStream that emits a pre-baked transcript script."""

    instances: list["FakeDGWithTranscripts"] = []
    script: list[TranscriptEvent] = []

    def __init__(self, *, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self.pushed: list[bytes] = []
        self.closed = False
        FakeDGWithTranscripts.instances.append(self)

    async def __aenter__(self) -> "FakeDGWithTranscripts":
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def push(self, frame: bytes) -> None:
        self.pushed.append(frame)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        # Emit each scripted event with a tiny sleep so the consumer can
        # interleave; then stay open until the pump task is cancelled.
        for ev in list(FakeDGWithTranscripts.script):
            await asyncio.sleep(0.01)
            yield ev
        while True:
            await asyncio.sleep(0.05)

    async def close(self) -> None:
        self.closed = True


class FakeDGRaisingEnter:
    """STT init blows up. Forces the `stt_unavailable` warn path."""

    def __init__(self, *, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate

    async def __aenter__(self) -> "FakeDGRaisingEnter":
        raise RuntimeError("DEEPGRAM_API_KEY not configured")

    async def __aexit__(self, *_):
        return None

    async def push(self, frame: bytes) -> None:  # pragma: no cover - never reached
        return None

    async def close(self) -> None:  # pragma: no cover - never reached
        return None


# ---------------------------------------------------------------------------


@pytest.fixture
def patch_ws_stt(db_engine, monkeypatch):
    url = db_engine.url.render_as_string(hide_password=False)
    sm = LoopBoundSessionLocal(url)
    monkeypatch.setattr(wcws, "SessionLocal", sm)
    monkeypatch.setattr(tmws, "SessionLocal", sm)
    monkeypatch.setattr(wcws, "Pipeline", FakePipeline)
    monkeypatch.setattr(tmws, "Pipeline", FakePipeline)
    FakeDGWithTranscripts.instances.clear()
    FakeDGWithTranscripts.script = []
    return sm


def _seed_web_call(loopbound) -> str:
    return _seed_call_sync(
        loopbound, direction="web", status="queued", first_message="hello"
    )


def test_stt_pump_emits_stt_frames_and_feeds_finals(patch_ws_stt, monkeypatch):
    """A non-final transcript → `type: stt` JSON only. A final transcript
    with `speech_final` → JSON event PLUS `pipe.feed_user_text(text, is_final=True)`.
    """
    FakeDGWithTranscripts.script = [
        TranscriptEvent(text="hel", is_final=False, speech_final=False, confidence=0.5),
        TranscriptEvent(text="hello world", is_final=True, speech_final=True, confidence=0.9),
    ]
    monkeypatch.setattr(wcws, "DeepgramStream", FakeDGWithTranscripts)

    call_id = _seed_web_call(patch_ws_stt)
    token = mint_ws_token(call_id)
    stt_payloads: list[dict] = []
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/{call_id}/ws?token={token}") as ws:
            ws.receive_json()  # started
            ws.receive_json()  # first message agent_text
            # Drain a handful of frames until we see both stt events plus
            # the echo'd agent_text triggered by feed_user_text.
            saw_echo = False
            for _ in range(20):
                ev = ws.receive_json()
                if ev.get("type") == "stt":
                    stt_payloads.append(ev)
                if ev.get("type") == "agent_text" and ev.get("text", "").startswith("echo:"):
                    saw_echo = True
                    break
            assert saw_echo, f"never saw echo agent_text; got {stt_payloads}"
            ws.send_json({"type": "hangup"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    # Both transcript events should have produced an `stt` frame.
    kinds = [p.get("is_final") for p in stt_payloads]
    assert False in kinds and True in kinds, f"missing interim/final stt: {stt_payloads}"
    final = [p for p in stt_payloads if p.get("is_final")][0]
    assert final["text"] == "hello world"
    assert final["speech_final"] is True


def test_stt_unavailable_emits_warn_and_keeps_session_alive(patch_ws_stt, monkeypatch):
    """STT __aenter__ raises → route sends `warn: stt_unavailable` and
    proceeds without a pump (text-mode-like). User text still flows."""
    monkeypatch.setattr(wcws, "DeepgramStream", FakeDGRaisingEnter)

    call_id = _seed_web_call(patch_ws_stt)
    token = mint_ws_token(call_id)
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/{call_id}/ws?token={token}") as ws:
            # Order of started + warn isn't guaranteed; collect first 3 frames.
            frames: list[dict[str, Any]] = []
            for _ in range(3):
                frames.append(ws.receive_json())
            warns = [f for f in frames if f.get("type") == "warn"]
            assert warns, f"no warn frame in {frames}"
            assert warns[0]["warn"] == "stt_unavailable"
            assert "detail" in warns[0]
            ws.send_json({"type": "user_text", "text": "hi", "is_final": True})
            # Echo proves pipeline still alive without STT.
            for _ in range(5):
                ev = ws.receive_json()
                if ev.get("type") == "agent_text" and ev.get("text") == "echo:hi":
                    break
            else:
                raise AssertionError("no echo after stt-unavailable warn")
            ws.send_json({"type": "hangup"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    status, kinds = _read_call_state(patch_ws_stt, call_id)
    assert status == "completed"
    assert "ws.closed" in kinds
