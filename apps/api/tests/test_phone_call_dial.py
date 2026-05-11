"""POST /v1/calls/phone wires up Telnyx initiate_call."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.routers import calls as calls_router


@pytest.fixture
def telnyx_configured(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telnyx_api_key", "tnx_test", raising=False)
    monkeypatch.setattr(s, "telnyx_connection_id", "conn_test", raising=False)
    yield


@pytest.fixture
def fake_telnyx(monkeypatch):
    client = AsyncMock()
    client.initiate_call = AsyncMock(
        return_value={"data": {"call_control_id": "cc_pstn_123"}}
    )
    client.aclose = AsyncMock()
    monkeypatch.setattr(calls_router, "_telnyx_client_factory", lambda: client)
    return client


@pytest.mark.asyncio
async def test_phone_dial_returns_503_when_unconfigured(client, auth_headers):
    s = get_settings()
    s.telnyx_api_key = ""
    s.telnyx_connection_id = ""
    # First make an agent so the 404 path doesn't fire
    r = await client.post(
        "/v1/agents",
        json={"name": "Dialer", "first_message": "Hi"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/calls/phone",
        json={"agent_id": agent_id, "from_number": "+15551112222", "to_number": "+15553334444"},
        headers=auth_headers,
    )
    assert r.status_code == 503, r.text


@pytest.mark.asyncio
async def test_phone_dial_calls_telnyx_and_stores_provider_id(
    client, auth_headers, telnyx_configured, fake_telnyx
):
    r = await client.post(
        "/v1/agents",
        json={"name": "Dialer2", "first_message": "Hi"},
        headers=auth_headers,
    )
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/calls/phone",
        json={"agent_id": agent_id, "from_number": "+15551112222", "to_number": "+15553334444"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "ringing"
    assert body["from_number"] == "+15551112222"
    assert body["to_number"] == "+15553334444"
    fake_telnyx.initiate_call.assert_awaited_once()
    kwargs = fake_telnyx.initiate_call.call_args.kwargs
    assert kwargs["to"] == "+15553334444"
    assert "stream_url" in kwargs and "call_id=" in kwargs["stream_url"]


@pytest.mark.asyncio
async def test_phone_dial_502_when_telnyx_errors(
    client, auth_headers, telnyx_configured, monkeypatch
):
    failing = AsyncMock()
    failing.initiate_call = AsyncMock(side_effect=RuntimeError("telnyx down"))
    failing.aclose = AsyncMock()
    monkeypatch.setattr(calls_router, "_telnyx_client_factory", lambda: failing)

    r = await client.post(
        "/v1/agents",
        json={"name": "Dialer3", "first_message": "Hi"},
        headers=auth_headers,
    )
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/calls/phone",
        json={"agent_id": agent_id, "from_number": "+15551112222", "to_number": "+15553334444"},
        headers=auth_headers,
    )
    assert r.status_code == 502, r.text
    assert "telnyx" in r.text.lower()
