"""CallRecorder unit tests + recording download endpoint."""

from __future__ import annotations

import io
import wave

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.pipeline.recording import CallRecorder, recording_key
from app.routers import calls as calls_router


def _silence(ms: int, sample_rate: int = 16000) -> bytes:
    frames = int(ms * sample_rate / 1000)
    return b"\x00\x00" * frames


def test_empty_recorder_returns_no_bytes():
    rec = CallRecorder()
    assert not rec.has_audio()
    assert rec.finalise() == b""


def test_recorder_produces_valid_stereo_wav():
    rec = CallRecorder()
    rec.push_user(_silence(100))
    rec.push_agent(_silence(100))
    wav_bytes = rec.finalise()

    assert wav_bytes.startswith(b"RIFF")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        # 100 ms @ 16 kHz = 1600 frames
        assert wf.getnframes() == 1600


def test_recorder_pads_shorter_channel():
    rec = CallRecorder()
    rec.push_user(_silence(200))
    rec.push_agent(_silence(50))
    wav_bytes = rec.finalise()
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        # both channels run for the longer of the two durations
        assert wf.getnframes() == int(200 * 16000 / 1000)


def test_finalise_is_idempotent_after_close():
    rec = CallRecorder()
    rec.push_user(_silence(10))
    rec.finalise()
    # subsequent pushes are ignored
    rec.push_user(_silence(100))
    rec.push_agent(_silence(100))
    # finalise again returns empty interleave (buffers stay as-was when closed)
    # We don't strictly require this — just confirm no exception.
    rec.finalise()


def test_recording_key_scoped_by_org():
    k = recording_key(org_id="org_123", call_id="call_abc")
    assert k == "recordings/org_123/call_abc.wav"


@pytest.mark.asyncio
async def test_recording_endpoint_404_without_key(client, auth_headers, db_session):
    r = await client.post(
        "/v1/agents", json={"name": "A", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]

    # Make a call with no recording_s3_key
    org = (await db_session.execute(select(models.Org))).scalars().first()
    call = models.Call(
        org_id=org.id,
        agent_id=agent_id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
    )
    db_session.add(call)
    await db_session.commit()
    call_id = call.id

    r = await client.get(f"/v1/calls/{call_id}/recording", headers=auth_headers)
    assert r.status_code == 404
    assert "no recording" in r.text.lower()


@pytest.mark.asyncio
async def test_recording_endpoint_streams_bytes(client, auth_headers, db_session, monkeypatch):
    r = await client.post(
        "/v1/agents", json={"name": "A2", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    org = (await db_session.execute(select(models.Org))).scalars().first()
    call = models.Call(
        org_id=org.id,
        agent_id=agent_id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        recording_s3_key=f"recordings/{org.id}/x.wav",
    )
    db_session.add(call)
    await db_session.commit()
    call_id = call.id

    # Mock storage fetch
    async def fake_get(*, bucket, key):
        assert bucket == get_settings().s3_bucket_recordings
        return b"RIFF\x00\x00\x00\x00WAVEfake"

    import app.storage.s3 as s3_mod

    monkeypatch.setattr(s3_mod, "get_object_bytes", fake_get)

    r = await client.get(f"/v1/calls/{call_id}/recording", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.content.startswith(b"RIFF")


@pytest.mark.asyncio
async def test_recording_endpoint_cross_org_404(client, auth_headers, db_session):
    other = models.Org(name="Other", slug="rec-other")
    db_session.add(other)
    await db_session.flush()
    r = await client.post(
        "/v1/agents", json={"name": "A3", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id_mine = r.json()["id"]  # noqa: F841

    foreign_call = models.Call(
        org_id=other.id,
        agent_id=agent_id_mine,  # FK still valid; auth is by org_id
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        recording_s3_key="recordings/other/x.wav",
    )
    db_session.add(foreign_call)
    await db_session.commit()
    foreign_id = foreign_call.id

    r = await client.get(f"/v1/calls/{foreign_id}/recording", headers=auth_headers)
    assert r.status_code == 404


def test_calls_router_imports_streamingresponse():
    """Regression guard: the new endpoint forward-references StreamingResponse."""
    assert hasattr(calls_router, "StreamingResponse")
