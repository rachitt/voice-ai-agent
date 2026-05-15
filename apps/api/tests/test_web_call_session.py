"""WS session token + web-call create endpoint wiring."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("VOICE_WEBHOOK_HMAC_SECRET", "test-hmac")

from app.pipeline.web_session import mint_ws_token, verify_ws_token  # noqa: E402


def test_mint_verify_roundtrip():
    t = mint_ws_token("call_abc123")
    assert verify_ws_token("call_abc123", t)
    assert not verify_ws_token("call_other", t)
    assert not verify_ws_token("call_abc123", t + "x")


def test_mint_is_deterministic():
    assert mint_ws_token("call_x") == mint_ws_token("call_x")


@pytest.mark.asyncio
async def test_create_web_call_returns_ws_token(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": "WC", "first_message": "Hello", "system_prompt": "be brief"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    r = await client.post(
        "/v1/calls/web",
        json={"agent_id": agent_id, "dynamic_variables": {"foo": "bar"}},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"].startswith("call_")
    assert body["direction"] == "web"
    assert body["ws_token"]
    assert body["ws_url"].startswith(f"/v1/calls/{body['id']}/ws?token=")
    assert verify_ws_token(body["id"], body["ws_token"])
