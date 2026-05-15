"""WS session loop coverage for web_call_ws + telnyx_media_ws.

Drives a real `websocket_connect` through FastAPI's TestClient against a
fake Pipeline + (for the PSTN flow) a fake STT, so the route's main
`receive → dispatch → finalise` block executes end-to-end without
hitting Deepgram / litellm / ElevenLabs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import models
from app.main import create_app
from app.pipeline.orchestrator import AgentConfig, PipelineEvent
from app.pipeline.web_session import mint_ws_token
from app.routers import telnyx_media_ws as tmws
from app.routers import web_call_ws as wcws


class FakePipeline:
    """Drops in for `Pipeline`. Emits started + records feed_user_text."""

    def __init__(self, cfg: AgentConfig, *, tool_dispatch=None) -> None:
        self.cfg = cfg
        self.fed: list[tuple[str, bool]] = []
        self._q: asyncio.Queue[PipelineEvent | None] = asyncio.Queue()
        self._started = False

    async def start(self) -> None:
        self._started = True
        await self._q.put(PipelineEvent(kind="started"))
        if self.cfg.first_message:
            await self._q.put(
                PipelineEvent(kind="agent_text", text=self.cfg.first_message, is_final=True)
            )

    async def feed_user_text(self, text: str, *, is_final: bool = True) -> None:
        self.fed.append((text, is_final))
        if is_final:
            # echo back as a tiny agent reply so _emit fires
            await self._q.put(PipelineEvent(kind="agent_text", text=f"echo:{text}", is_final=True))

    async def events(self) -> AsyncIterator[PipelineEvent]:
        while True:
            ev = await self._q.get()
            if ev is None:
                return
            yield ev

    async def close(self) -> None:
        await self._q.put(None)


class FakeDG:
    """Drop-in DeepgramStream for the PSTN session pump."""

    instances: list[FakeDG] = []

    def __init__(self, *, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        self.pushed: list[bytes] = []
        self.closed = False
        FakeDG.instances.append(self)

    async def __aenter__(self) -> FakeDG:
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def push(self, frame: bytes) -> None:
        self.pushed.append(frame)

    async def events(self) -> AsyncIterator:
        # Stay open until cancelled; the session loop cancels the pump task in finally.
        if False:
            yield  # type: ignore[unreachable] - mark as async generator
        while True:
            await asyncio.sleep(0.05)

    async def close(self) -> None:
        self.closed = True


class LoopBoundSessionLocal:
    """Build a fresh AsyncEngine+sessionmaker on first call in each event loop.

    TestClient runs the ASGI app in its own thread w/ its own asyncio loop;
    using the test's `db_engine` from that loop blows up with
    "Future attached to a different loop". Defer engine creation until the
    route asks for a session and cache per-loop.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._cache: dict[int, async_sessionmaker] = {}

    def __call__(self):
        loop = asyncio.get_event_loop()
        key = id(loop)
        sm = self._cache.get(key)
        if sm is None:
            engine = create_async_engine(self._url, pool_pre_ping=True)
            sm = async_sessionmaker(engine, expire_on_commit=False)
            self._cache[key] = sm
        return sm()


@pytest.fixture
def patch_ws_runtime(db_engine, monkeypatch):
    """Wire router-local module names to test doubles + the test DB."""
    url = db_engine.url.render_as_string(hide_password=False)
    test_sessionmaker = LoopBoundSessionLocal(url)
    monkeypatch.setattr(wcws, "SessionLocal", test_sessionmaker)
    monkeypatch.setattr(tmws, "SessionLocal", test_sessionmaker)
    monkeypatch.setattr(wcws, "Pipeline", FakePipeline)
    monkeypatch.setattr(tmws, "Pipeline", FakePipeline)
    monkeypatch.setattr(wcws, "DeepgramStream", FakeDG)
    monkeypatch.setattr(tmws, "DeepgramStream", FakeDG)
    FakeDG.instances.clear()
    return test_sessionmaker


def _run_in_fresh_loop(coro_factory):
    """Spin a brand-new event loop just for a one-shot async DB op.

    The test loop has already serviced TestClient; we can't share it
    with another asyncpg connection without "different loop" pain.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


async def _read_call_state_async(url: str, call_id: str):
    eng = create_async_engine(url, pool_pre_ping=True)
    try:
        async with eng.connect() as c:
            status = (
                await c.execute(text("SELECT status FROM calls WHERE id = :id"), {"id": call_id})
            ).scalar_one()
            rows = (
                await c.execute(
                    text("SELECT kind FROM call_events WHERE call_id = :id"), {"id": call_id}
                )
            ).all()
        return status, [r[0] for r in rows]
    finally:
        await eng.dispose()


def _read_call_state(loopbound, call_id: str) -> tuple[str, list[str]]:
    return _run_in_fresh_loop(lambda: _read_call_state_async(loopbound._url, call_id))


def _await_call_state(
    loopbound, call_id: str, *, expected_status: str, timeout: float = 3.0
) -> tuple[str, list[str]]:
    """Poll the DB until the route's finally-block has committed completion."""
    import time as _t

    deadline = _t.time() + timeout
    last: tuple[str, list[str]] = ("", [])
    while _t.time() < deadline:
        last = _read_call_state(loopbound, call_id)
        if last[0] == expected_status:
            return last
        _t.sleep(0.05)
    return last


async def _seed_call_async(
    url: str, *, direction: str, status: str, first_message: str | None
) -> str:
    import uuid as _u

    eng = create_async_engine(url, pool_pre_ping=True)
    org_id = "org_" + _u.uuid4().hex[:8]
    agent_id = "ag_" + _u.uuid4().hex[:8]
    ver_id = "agv_" + _u.uuid4().hex[:8]
    call_id = "call_" + _u.uuid4().hex[:8]
    now = datetime.now(UTC)
    try:
        async with eng.begin() as c:
            await c.execute(
                text(
                    "INSERT INTO orgs (id, name, slug, created_at, updated_at) "
                    "VALUES (:id, :n, :s, :ts, :ts)"
                ),
                {"id": org_id, "n": "O", "s": f"ws-{_u.uuid4().hex[:6]}", "ts": now},
            )
            await c.execute(
                text(
                    "INSERT INTO agents (id, org_id, name, created_at, updated_at) "
                    "VALUES (:id, :org, :n, :ts, :ts)"
                ),
                {"id": agent_id, "org": org_id, "n": "A", "ts": now},
            )
            await c.execute(
                text(
                    "INSERT INTO agent_versions "
                    "(id, agent_id, version, env, first_message, system_prompt, "
                    " model_id, voice_id, stt_id, language, interruption_sensitivity, "
                    " vad_silence_ms, tools, knowledge_base_ids, dynamic_variables, "
                    " created_at, updated_at) "
                    "VALUES (:id, :ag, 1, 'draft', :fm, 'be brief', "
                    " 'gemini/gemini-3.1-flash-lite', '21m00Tcm4TlvDq8ikWAM', 'deepgram-nova-3', 'en', "
                    " 0.5, 700, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, :ts, :ts)"
                ),
                {"id": ver_id, "ag": agent_id, "fm": first_message, "ts": now},
            )
            await c.execute(
                text(
                    "INSERT INTO calls "
                    "(id, org_id, agent_id, agent_version_id, direction, status, "
                    " dynamic_variables, started_at, created_at, updated_at) "
                    "VALUES (:id, :org, :ag, :ver, :dir, :st, '{}'::jsonb, :ts, :ts, :ts)"
                ),
                {
                    "id": call_id,
                    "org": org_id,
                    "ag": agent_id,
                    "ver": ver_id,
                    "dir": direction,
                    "st": status,
                    "ts": now,
                },
            )
        return call_id
    finally:
        await eng.dispose()


def _seed_call_sync(loopbound, *, direction: str, status: str, first_message: str | None) -> str:
    return _run_in_fresh_loop(
        lambda: _seed_call_async(
            loopbound._url, direction=direction, status=status, first_message=first_message
        )
    )


@pytest.fixture
def seeded_web_call_sync(patch_ws_runtime) -> str:
    return _seed_call_sync(
        patch_ws_runtime, direction="web", status="queued", first_message="hi there"
    )


@pytest.fixture
def seeded_pstn_call_sync(patch_ws_runtime) -> str:
    return _seed_call_sync(
        patch_ws_runtime, direction="inbound", status="ringing", first_message=None
    )


@pytest.fixture
async def seeded_web_call(db_session):
    """Seed an org + agent + agent version + queued web call."""
    org = models.Org(name="O", slug=f"ws-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id,
        version=1,
        first_message="hi there",
        system_prompt="be brief",
        tools=[],
        knowledge_base_ids=[],
    )
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        agent_version_id=ver.id,
        direction="web",
        status="queued",
        dynamic_variables={},
    )
    db_session.add(call)
    await db_session.commit()
    return call


@pytest.fixture
async def seeded_pstn_call(db_session):
    org = models.Org(name="O", slug=f"pstn-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id, version=1, first_message=None, tools=[], knowledge_base_ids=[]
    )
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        agent_version_id=ver.id,
        direction="inbound",
        status="ringing",
        provider_call_id="cc_ws_test",
        from_number="+15558881111",
        to_number="+15557772222",
        started_at=datetime.now(UTC),
        dynamic_variables={},
    )
    db_session.add(call)
    await db_session.commit()
    return call


# ---------- web_call_ws --------------------------------------------------------


def test_web_call_ws_rejects_bad_token(patch_ws_runtime):
    """Invalid token: WS accept never happens; close code 1008."""
    with TestClient(create_app()) as tc:
        with pytest.raises(Exception):
            with tc.websocket_connect("/v1/calls/call_x/ws?token=bad"):
                pass


def test_web_call_ws_404_for_unknown_call(patch_ws_runtime):
    """Valid token format, but call row doesn't exist → error JSON + close."""
    from starlette.websockets import WebSocketDisconnect

    token = mint_ws_token("call_ghost")
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/call_ghost/ws?token={token}") as ws:
            msg = ws.receive_json()
            assert msg.get("error") == "call_not_found"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_web_call_ws_text_only_full_session(patch_ws_runtime, seeded_web_call_sync):
    """Connect, receive started + first_message, send user_text, get echo, hangup."""
    from starlette.websockets import WebSocketDisconnect

    call_id = seeded_web_call_sync
    token = mint_ws_token(call_id)
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/{call_id}/ws?token={token}&text_only=true") as ws:
            ev1 = ws.receive_json()
            assert ev1["type"] == "started"
            ev2 = ws.receive_json()
            assert ev2["type"] == "agent_text"
            assert ev2["text"] == "hi there"
            ws.send_json({"type": "user_text", "text": "hello", "is_final": True})
            ev3 = ws.receive_json()
            assert ev3["type"] == "agent_text"
            assert ev3["text"] == "echo:hello"
            ws.send_json({"type": "hangup"})
            # Block on the server close so the finally-block finalise runs.
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    status, kinds = _read_call_state(patch_ws_runtime, call_id)
    assert status == "completed"
    assert "ws.closed" in kinds


def test_web_call_ws_skips_invalid_json_text(seeded_web_call_sync):
    """Garbage text frames are dropped silently — session stays alive."""
    call_id = seeded_web_call_sync
    token = mint_ws_token(call_id)
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/{call_id}/ws?token={token}&text_only=true") as ws:
            ws.receive_json()  # started
            ws.receive_json()  # first message
            ws.send_text("not-json")
            ws.send_json({"type": "user_text", "text": "after", "is_final": True})
            ev = ws.receive_json()
            assert ev["text"] == "echo:after"
            ws.send_json({"type": "hangup"})


def test_web_call_ws_pushes_binary_frame_to_stt(seeded_web_call_sync):
    """Binary PCM frames hit the recorder + STT push path (text_only=false)."""
    call_id = seeded_web_call_sync
    token = mint_ws_token(call_id)
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(f"/v1/calls/{call_id}/ws?token={token}") as ws:
            ws.receive_json()
            ws.receive_json()
            ws.send_bytes(b"\x01\x02\x03\x04")
            ws.send_json({"type": "hangup"})
    # FakeDG.instances captures pushes if STT branch ran.
    assert any(b"\x01\x02\x03\x04" in dg.pushed for dg in FakeDG.instances)


# ---------- telnyx_media_ws ----------------------------------------------------


def test_telnyx_ws_rejects_bad_token(patch_ws_runtime):
    with TestClient(create_app()) as tc:
        with pytest.raises(Exception):
            with tc.websocket_connect("/v1/telephony/telnyx/media?call_id=call_x&token=bad"):
                pass


def test_telnyx_ws_404_for_unknown_call(patch_ws_runtime):
    from starlette.websockets import WebSocketDisconnect

    token = mint_ws_token("call_ghost_pstn")
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(
            f"/v1/telephony/telnyx/media?call_id=call_ghost_pstn&token={token}"
        ) as ws:
            msg = ws.receive_json()
            assert msg.get("error") == "call_not_found"
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_telnyx_ws_handles_start_media_stop(patch_ws_runtime, seeded_pstn_call_sync):
    """Full Telnyx envelope sequence: start → media → stop."""
    from starlette.websockets import WebSocketDisconnect

    call_id = seeded_pstn_call_sync
    token = mint_ws_token(call_id)
    # 8 zero-ulaw bytes → decodes to silence
    ulaw_payload = base64.b64encode(b"\x7f" * 8).decode()
    with TestClient(create_app()) as tc:
        with tc.websocket_connect(
            f"/v1/telephony/telnyx/media?call_id={call_id}&token={token}"
        ) as ws:
            ws.send_text(
                json.dumps({"event": "start", "start": {"streamId": "s1", "callSid": "cc_x"}})
            )
            ws.send_text(json.dumps({"event": "media", "media": {"payload": ulaw_payload}}))
            # garbage payload exercises decode error path
            ws.send_text(json.dumps({"event": "media", "media": {"payload": "!!!not-b64!!!"}}))
            # not-json line exercises decode-error continue
            ws.send_text("totally-not-json")
            # Receive the started envelope to give the server a sync point.
            started_envelope = ws.receive_text()
            assert "voice2.started" in started_envelope
            ws.send_text(json.dumps({"event": "stop"}))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
    status, kinds = _await_call_state(
        patch_ws_runtime, call_id, expected_status="completed", timeout=8.0
    )
    assert status == "completed", f"got status={status} kinds={kinds}"
    assert "telnyx.media.closed" in kinds
    assert any(dg.pushed for dg in FakeDG.instances)
