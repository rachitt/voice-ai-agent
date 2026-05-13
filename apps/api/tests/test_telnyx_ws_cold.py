"""Cold-spot coverage for `telnyx_media_ws`:
- `agent_version_missing` branch (cfg = None)
- `stt_unavailable` log path (PSTN side)
- `_stt_pump` text+speech_final branches
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.pipeline.stt import TranscriptEvent
from app.pipeline.web_session import mint_ws_token
from app.routers import telnyx_media_ws as tmws
from app.routers import web_call_ws as wcws

from tests.test_ws_session_loop import (
    FakePipeline,
    LoopBoundSessionLocal,
    _await_call_state,
    _run_in_fresh_loop,
    _seed_call_sync,
)


class _DGYields:
    instances: list["_DGYields"] = []
    script: list[TranscriptEvent] = []

    def __init__(self, *, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self.pushed: list[bytes] = []
        _DGYields.instances.append(self)

    async def __aenter__(self) -> "_DGYields":
        return self

    async def __aexit__(self, *_):
        return None

    async def push(self, frame: bytes) -> None:
        self.pushed.append(frame)

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        for ev in list(_DGYields.script):
            await asyncio.sleep(0.01)
            yield ev
        while True:
            await asyncio.sleep(0.05)

    async def close(self) -> None:
        return None


class _DGRaises:
    def __init__(self, *, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate

    async def __aenter__(self):
        raise RuntimeError("DEEPGRAM_API_KEY not configured")

    async def __aexit__(self, *_):
        return None

    async def push(self, frame: bytes) -> None:  # pragma: no cover
        return None

    async def close(self) -> None:  # pragma: no cover
        return None


@pytest.fixture
def patch_pstn(db_engine, monkeypatch):
    url = db_engine.url.render_as_string(hide_password=False)
    sm = LoopBoundSessionLocal(url)
    monkeypatch.setattr(wcws, "SessionLocal", sm)
    monkeypatch.setattr(tmws, "SessionLocal", sm)
    monkeypatch.setattr(wcws, "Pipeline", FakePipeline)
    monkeypatch.setattr(tmws, "Pipeline", FakePipeline)
    _DGYields.instances.clear()
    _DGYields.script = []
    return sm


def _seed_pstn(loopbound) -> str:
    return _seed_call_sync(
        loopbound, direction="inbound", status="ringing", first_message=None
    )


def test_telnyx_ws_missing_agent_version_errors(patch_pstn, monkeypatch):
    """When the agent version is wiped before the WS connects, the route
    sends `agent_version_missing` + closes 1008."""
    monkeypatch.setattr(tmws, "DeepgramStream", _DGYields)
    call_id = _seed_pstn(patch_pstn)
    # Strip the agent_version row so _build_agent_config returns None.
    async def _wipe():
        from sqlalchemy.ext.asyncio import create_async_engine

        eng = create_async_engine(patch_pstn._url, pool_pre_ping=True)
        try:
            async with eng.begin() as c:
                await c.execute(text("UPDATE calls SET agent_version_id = NULL WHERE id = :id"), {"id": call_id})
                await c.execute(text("DELETE FROM agent_versions"))
        finally:
            await eng.dispose()

    _run_in_fresh_loop(_wipe)

    token = mint_ws_token(call_id)
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(
            f"/v1/telephony/telnyx/media?call_id={call_id}&token={token}"
        ) as ws:
            msg = ws.receive_json()
            assert msg.get("error") == "agent_version_missing"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_telnyx_stt_pump_feeds_finals(patch_pstn, monkeypatch):
    """`_stt_pump` should call `pipe.feed_user_text` when a final transcript
    arrives — assert via the FakePipeline echoing back agent_text."""
    _DGYields.script = [
        TranscriptEvent(text="user words", is_final=True, speech_final=True, confidence=0.9),
    ]
    monkeypatch.setattr(tmws, "DeepgramStream", _DGYields)

    call_id = _seed_pstn(patch_pstn)
    token = mint_ws_token(call_id)
    ulaw = base64.b64encode(b"\x7f" * 8).decode()
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(
            f"/v1/telephony/telnyx/media?call_id={call_id}&token={token}"
        ) as ws:
            ws.send_text(json.dumps({"event": "start", "start": {"streamId": "s1"}}))
            ws.send_text(json.dumps({"event": "media", "media": {"payload": ulaw}}))
            # Drain envelopes until the echo'd agent_text appears.
            saw_echo = False
            for _ in range(30):
                msg = ws.receive_text()
                if "voice2.agent_text" in msg and "echo:user words" in msg:
                    saw_echo = True
                    break
            assert saw_echo
            ws.send_text(json.dumps({"event": "stop"}))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()

    status, kinds = _await_call_state(
        patch_pstn, call_id, expected_status="completed", timeout=8.0
    )
    assert status == "completed"
    assert "telnyx.media.closed" in kinds


def test_telnyx_stt_unavailable_proceeds_without_pump(patch_pstn, monkeypatch):
    """STT init raises — route logs warn, stt becomes None, session still
    completes when client sends stop."""
    monkeypatch.setattr(tmws, "DeepgramStream", _DGRaises)
    call_id = _seed_pstn(patch_pstn)
    token = mint_ws_token(call_id)
    ulaw = base64.b64encode(b"\x7f" * 8).decode()
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(
            f"/v1/telephony/telnyx/media?call_id={call_id}&token={token}"
        ) as ws:
            ws.send_text(json.dumps({"event": "start", "start": {"streamId": "s1"}}))
            # Media w/ stt=None hits the continue branch.
            ws.send_text(json.dumps({"event": "media", "media": {"payload": ulaw}}))
            # Consume the auto-sent first envelope to give the server a sync point.
            ws.receive_text()
            ws.send_text(json.dumps({"event": "stop"}))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()

    status, _ = _await_call_state(
        patch_pstn, call_id, expected_status="completed", timeout=8.0
    )
    assert status == "completed"
