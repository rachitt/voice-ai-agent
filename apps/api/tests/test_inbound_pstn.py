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
        await db_session.execute(
            select(models.Call).where(models.Call.provider_call_id == cc_id)
        )
    ).scalar_one()
    assert call.direction == models.CallDirection.inbound
    assert call.status == models.CallStatus.ringing
    assert call.from_number == "+15558889999"
    assert call.to_number == "+15557770001"
    assert call.agent_id == agent_id


@pytest.mark.asyncio
async def test_inbound_unknown_number_does_not_answer(
    client, telnyx_unsigned, fake_telnyx
):
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
async def test_inbound_initiated_idempotent(
    client, auth_headers, telnyx_unsigned, fake_telnyx
):
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
