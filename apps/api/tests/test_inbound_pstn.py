"""Telnyx inbound PSTN: call.initiated → answer with media stream."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db import models
from app.routers import webhooks as webhooks_router


@pytest.fixture
def telnyx_unsigned(monkeypatch):
    """Disable signature verify so we can POST a raw payload."""
    s = get_settings()
    monkeypatch.setattr(s, "telnyx_webhook_public_key", "", raising=False)
    yield


@pytest.fixture
def fake_telnyx(monkeypatch):
    cli = AsyncMock()
    cli.answer = AsyncMock(return_value={"data": {}})
    cli.aclose = AsyncMock()
    monkeypatch.setattr(webhooks_router, "_telnyx_client_factory", lambda: cli)
    return cli


@pytest.mark.asyncio
async def test_inbound_call_initiated_creates_call_and_answers(
    client, db_session, auth_headers, telnyx_unsigned, fake_telnyx
):
    # Create agent and phone number bound to that agent.
    r = await client.post(
        "/v1/agents", json={"name": "Receptionist", "first_message": "Hi"}, headers=auth_headers
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770001", "provider": "telnyx", "agent_id": agent_id},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text

    cc_id = "cc_inbound_abc"
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": cc_id,
                "direction": "incoming",
                "to": "+15557770001",
                "from": "+15558889999",
            },
        }
    }
    r = await client.post("/v1/webhooks/telnyx", json=payload)
    assert r.status_code == 204, r.text

    # Telnyx answer invoked with stream_url that points at our media WS.
    fake_telnyx.answer.assert_awaited_once()
    kwargs = fake_telnyx.answer.call_args.kwargs
    args = fake_telnyx.answer.call_args.args
    assert args[0] == cc_id
    assert "stream_url" in kwargs and "call_id=" in kwargs["stream_url"]
    assert "/v1/telephony/telnyx/media" in kwargs["stream_url"]

    # Call row exists with direction=inbound, status=ringing.
    call = (
        await db_session.execute(select(models.Call).where(models.Call.provider_call_id == cc_id))
    ).scalar_one()
    assert call.direction == models.CallDirection.inbound
    assert call.status == models.CallStatus.ringing
    assert call.from_number == "+15558889999"
    assert call.to_number == "+15557770001"
    assert call.agent_id == agent_id


@pytest.mark.asyncio
async def test_inbound_unknown_number_does_not_answer(client, telnyx_unsigned, fake_telnyx):
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": "cc_orphan",
                "direction": "incoming",
                "to": "+15550000000",
                "from": "+15558889999",
            },
        }
    }
    r = await client.post("/v1/webhooks/telnyx", json=payload)
    assert r.status_code == 204
    fake_telnyx.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_bad_json_returns_400(client, telnyx_unsigned):
    r = await client.post(
        "/v1/webhooks/telnyx", content=b"not-json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_missing_cc_returns_204(client, telnyx_unsigned, fake_telnyx):
    # Payload with no call_control_id is acknowledged but no-op.
    r = await client.post(
        "/v1/webhooks/telnyx",
        json={"data": {"event_type": "system.ping", "payload": {}}},
    )
    assert r.status_code == 204
    fake_telnyx.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_bad_signature_returns_401(client, monkeypatch):
    """When public key is configured, missing/invalid signature → 401."""
    s = get_settings()
    monkeypatch.setattr(s, "telnyx_webhook_public_key", "fake-pub-key", raising=False)
    r = await client.post(
        "/v1/webhooks/telnyx",
        json={"data": {"event_type": "call.initiated", "payload": {}}},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_call_answered_updates_status(
    client, db_session, auth_headers, telnyx_unsigned, fake_telnyx
):
    """Pre-existing Call: call.answered transitions ringing → in_progress."""
    r = await client.post("/v1/agents", json={"name": "Rcv"}, headers=auth_headers)
    agent_id = r.json()["id"]
    await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770099", "provider": "telnyx", "agent_id": agent_id},
        headers=auth_headers,
    )
    cc = "cc_answered_x"
    init = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": cc,
                "direction": "incoming",
                "to": "+15557770099",
                "from": "+15558881111",
            },
        }
    }
    await client.post("/v1/webhooks/telnyx", json=init)
    # Now send answered.
    answered = {"data": {"event_type": "call.answered", "payload": {"call_control_id": cc}}}
    r = await client.post("/v1/webhooks/telnyx", json=answered)
    assert r.status_code == 204

    call = (
        await db_session.execute(select(models.Call).where(models.Call.provider_call_id == cc))
    ).scalar_one()
    assert call.status == models.CallStatus.in_progress
    assert call.started_at is not None


@pytest.mark.asyncio
async def test_webhook_call_hangup_computes_duration(
    client, db_session, auth_headers, telnyx_unsigned, fake_telnyx
):
    r = await client.post("/v1/agents", json={"name": "Rcv2"}, headers=auth_headers)
    agent_id = r.json()["id"]
    await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770100", "provider": "telnyx", "agent_id": agent_id},
        headers=auth_headers,
    )
    cc = "cc_hangup_y"
    seed = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": cc,
                "direction": "incoming",
                "to": "+15557770100",
                "from": "+15558881111",
            },
        }
    }
    await client.post("/v1/webhooks/telnyx", json=seed)
    await client.post(
        "/v1/webhooks/telnyx",
        json={"data": {"event_type": "call.answered", "payload": {"call_control_id": cc}}},
    )
    await client.post(
        "/v1/webhooks/telnyx",
        json={"data": {"event_type": "call.hangup", "payload": {"call_control_id": cc}}},
    )
    call = (
        await db_session.execute(select(models.Call).where(models.Call.provider_call_id == cc))
    ).scalar_one()
    assert call.status == models.CallStatus.completed
    assert call.ended_at is not None
    assert call.duration_ms is not None and call.duration_ms >= 0


@pytest.mark.asyncio
async def test_inbound_initiated_no_to_field(client, telnyx_unsigned, fake_telnyx):
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {"call_control_id": "cc_no_to", "direction": "incoming"},
        }
    }
    r = await client.post("/v1/webhooks/telnyx", json=payload)
    assert r.status_code == 204
    fake_telnyx.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_inbound_answer_failure_marks_call_failed(
    client, db_session, auth_headers, telnyx_unsigned, fake_telnyx
):
    """If telnyx.answer raises, call row is marked failed and aclose still runs."""
    r = await client.post("/v1/agents", json={"name": "Rcv3"}, headers=auth_headers)
    agent_id = r.json()["id"]
    await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770133", "provider": "telnyx", "agent_id": agent_id},
        headers=auth_headers,
    )
    fake_telnyx.answer.side_effect = RuntimeError("telnyx down")
    cc = "cc_fail_z"
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": cc,
                "direction": "incoming",
                "to": "+15557770133",
                "from": "+15558881111",
            },
        }
    }
    r = await client.post("/v1/webhooks/telnyx", json=payload)
    assert r.status_code == 204
    call = (
        await db_session.execute(select(models.Call).where(models.Call.provider_call_id == cc))
    ).scalar_one()
    assert call.status == models.CallStatus.failed
    fake_telnyx.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_inbound_initiated_idempotent(client, auth_headers, telnyx_unsigned, fake_telnyx):
    r = await client.post(
        "/v1/agents", json={"name": "Recep2", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770002", "provider": "telnyx", "agent_id": agent_id},
        headers=auth_headers,
    )
    payload = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": "cc_dup",
                "direction": "incoming",
                "to": "+15557770002",
                "from": "+15558889999",
            },
        }
    }
    await client.post("/v1/webhooks/telnyx", json=payload)
    await client.post("/v1/webhooks/telnyx", json=payload)
    assert fake_telnyx.answer.await_count == 1
