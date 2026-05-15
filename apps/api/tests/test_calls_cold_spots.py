"""calls router: uncovered paths — status/direction filters, recording URLs,
recording stream, SSE generator handshake."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.db import models


async def _make_call(
    db_session,
    *,
    agent_id: str,
    org_id: str,
    status="completed",
    direction="web",
    recording_s3_key: str | None = None,
):
    call = models.Call(
        org_id=org_id,
        agent_id=agent_id,
        direction=direction,
        status=status,
        recording_s3_key=recording_s3_key,
    )
    db_session.add(call)
    await db_session.commit()
    await db_session.refresh(call)
    return call


async def _bootstrap_agent(client, auth_headers) -> str:
    r = await client.post(
        "/v1/agents", headers=auth_headers, json={"name": f"A-{uuid.uuid4().hex[:4]}"}
    )
    return r.json()["id"]


async def _org_id_for(client, auth_headers) -> str:
    """Pull org id off any returned agent — simpler than re-reading principal."""
    r = await client.post(
        "/v1/agents", headers=auth_headers, json={"name": f"O-{uuid.uuid4().hex[:4]}"}
    )
    return r.json()["org_id"]


# ----- list filters: status + direction -------------------------------------


@pytest.mark.asyncio
async def test_list_filters_by_status(client, db_session, auth_headers):
    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    await _make_call(db_session, agent_id=agent_id, org_id=org_id, status="completed")
    await _make_call(db_session, agent_id=agent_id, org_id=org_id, status="failed")
    r = await client.get("/v1/calls?status=failed", headers=auth_headers)
    assert r.status_code == 200
    statuses = {c["status"] for c in r.json()["items"]}
    assert statuses == {"failed"}


@pytest.mark.asyncio
async def test_list_filters_by_direction(client, db_session, auth_headers):
    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    await _make_call(db_session, agent_id=agent_id, org_id=org_id, direction="web")
    await _make_call(db_session, agent_id=agent_id, org_id=org_id, direction="inbound")
    r = await client.get("/v1/calls?direction=inbound", headers=auth_headers)
    assert r.status_code == 200
    dirs = {c["direction"] for c in r.json()["items"]}
    assert dirs == {"inbound"}


# ----- get_call 404 ----------------------------------------------------------


@pytest.mark.asyncio
async def test_get_call_404(client, auth_headers):
    r = await client.get("/v1/calls/call_missing", headers=auth_headers)
    assert r.status_code == 404


# ----- recording-url branches -----------------------------------------------


@pytest.mark.asyncio
async def test_recording_url_404_for_unknown_call(client, auth_headers):
    r = await client.get("/v1/calls/call_missing/recording-url", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_recording_url_404_when_no_recording(client, db_session, auth_headers):
    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(db_session, agent_id=agent_id, org_id=org_id)
    r = await client.get(f"/v1/calls/{call.id}/recording-url", headers=auth_headers)
    assert r.status_code == 404
    assert "no recording" in r.json()["detail"]


@pytest.mark.asyncio
async def test_recording_url_returns_null_when_storage_disabled(
    client, db_session, auth_headers, monkeypatch
):
    """If enable_object_store=False, presign returns None and we surface url=null."""
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.delenv("VOICE_ENABLE_OBJECT_STORE", raising=False)
    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(
        db_session, agent_id=agent_id, org_id=org_id, recording_s3_key="rec/x.wav"
    )
    r = await client.get(f"/v1/calls/{call.id}/recording-url", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["url"] is None
    assert body["expires_in"] == 600


@pytest.mark.asyncio
async def test_recording_url_returns_signed_when_enabled(
    client, db_session, auth_headers, monkeypatch
):
    from app.core import config as cfg
    from app.storage import s3

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_OBJECT_STORE", "true")

    async def fake_to_thread(fn, *args, **kw):
        return fn(*args, **kw)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(s3, "_presign_get_sync", lambda b, k, e, ct: f"https://s3/{b}/{k}")

    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(
        db_session, agent_id=agent_id, org_id=org_id, recording_s3_key="rec/song.wav"
    )
    r = await client.get(f"/v1/calls/{call.id}/recording-url", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["url"] and "rec/song.wav" in body["url"]
    cfg.get_settings.cache_clear()


# ----- recording stream branches --------------------------------------------


@pytest.mark.asyncio
async def test_recording_stream_404_for_unknown_call(client, auth_headers):
    r = await client.get("/v1/calls/call_missing/recording", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_recording_stream_404_when_no_recording(client, db_session, auth_headers):
    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(db_session, agent_id=agent_id, org_id=org_id)
    r = await client.get(f"/v1/calls/{call.id}/recording", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_recording_stream_serves_bytes(client, db_session, auth_headers, monkeypatch):
    from app.storage import s3

    async def fake_to_thread(fn, *args, **kw):
        return b"RIFF....WAVEdata...."

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(s3, "_get_sync", lambda b, k: b"RIFF....WAVEdata....")

    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(
        db_session, agent_id=agent_id, org_id=org_id, recording_s3_key="rec/x.wav"
    )
    r = await client.get(f"/v1/calls/{call.id}/recording", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert "attachment" in r.headers["content-disposition"]
    assert r.content == b"RIFF....WAVEdata...."


@pytest.mark.asyncio
async def test_recording_stream_returns_502_on_fetch_error(
    client, db_session, auth_headers, monkeypatch
):
    from app.storage import s3

    async def fake_to_thread(fn, *args, **kw):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(s3, "_get_sync", lambda b, k: (_ for _ in ()).throw(RuntimeError("nope")))

    agent_id = await _bootstrap_agent(client, auth_headers)
    org_id = (
        await db_session.execute(
            __import__("sqlalchemy").select(models.Agent.org_id).where(models.Agent.id == agent_id)
        )
    ).scalar_one()
    call = await _make_call(
        db_session, agent_id=agent_id, org_id=org_id, recording_s3_key="rec/x.wav"
    )
    r = await client.get(f"/v1/calls/{call.id}/recording", headers=auth_headers)
    assert r.status_code == 502


# ----- SSE stream handshake -------------------------------------------------


@pytest.mark.asyncio
async def test_sse_stream_404_for_unknown_call(client, auth_headers):
    """Routing path with org_id resolved via bearer; 404 for unknown call."""
    r = await client.get("/v1/calls/call_missing/stream", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_sse_principal_via_bearer_empty_token(client):
    """Bearer header with empty token after the prefix is rejected."""
    r = await client.get("/v1/calls/call_x/stream", headers={"Authorization": "Bearer  "})
    # No principal, no query token → 401 missing credentials.
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_sse_principal_via_bearer_invalid_key(client):
    """Bearer with a non-matching key falls through to 401."""
    r = await client.get(
        "/v1/calls/call_x/stream", headers={"Authorization": "Bearer sk_test_unknown_key"}
    )
    assert r.status_code == 401
