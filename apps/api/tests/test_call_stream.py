"""GET /v1/calls/:id/stream — SSE endpoint smoke."""

from __future__ import annotations

import pytest

from app.pipeline.web_session import mint_sse_token


@pytest.mark.asyncio
async def test_stream_404_for_unknown_call(client, auth_headers):
    r = await client.get("/v1/calls/call_nope/stream", headers=auth_headers)
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_stream_401_without_auth(client):
    r = await client.get("/v1/calls/call_nope/stream")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_rejects_raw_api_key_in_query(client, auth_headers):
    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    r = await client.get(f"/v1/calls/call_nope/stream?token={bearer}")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_token_endpoint_mints_short_lived_token(client, auth_headers):
    r = await client.post("/v1/agents", json={"name": "Streamer"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]
    r = await client.post("/v1/calls/web", json={"agent_id": agent_id}, headers=auth_headers)
    assert r.status_code == 201, r.text
    call_id = r.json()["id"]

    r = await client.post(f"/v1/calls/{call_id}/stream-token", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ttl_seconds"] == 300
    assert "." in body["token"]
    assert body["expires_at"] > 0


@pytest.mark.asyncio
async def test_stream_rejects_token_for_different_call(client):
    spoofed = mint_sse_token("call_other", "org_other")[0]
    r = await client.get(f"/v1/calls/call_target/stream?token={spoofed}")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_token_requires_call_ownership(client, auth_headers):
    r = await client.post("/v1/calls/call_nope/stream-token", headers=auth_headers)
    assert r.status_code == 404, r.text
