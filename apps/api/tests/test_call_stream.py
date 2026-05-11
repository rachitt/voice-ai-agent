"""GET /v1/calls/:id/stream — SSE endpoint smoke."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_stream_404_for_unknown_call(client, auth_headers):
    r = await client.get("/v1/calls/call_nope/stream", headers=auth_headers)
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_stream_401_without_auth(client):
    r = await client.get("/v1/calls/call_nope/stream")
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_accepts_query_token(client, auth_headers):
    # Grab the bearer token from the header
    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    # Unknown call still hits auth first; 404 means token was accepted
    r = await client.get(f"/v1/calls/call_nope/stream?token={bearer}")
    assert r.status_code == 404, r.text
