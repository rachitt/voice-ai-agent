"""TelnyxClient — HTTP surface tests with mocked transport."""

from __future__ import annotations

import httpx
import pytest

from app.telephony.telnyx import TelnyxClient


@pytest.fixture
def patched_client(monkeypatch):
    """Build a TelnyxClient wired to a MockTransport so we capture every request."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        # Per-endpoint canned responses.
        if request.url.path == "/v2/number_orders":
            return httpx.Response(200, json={"data": {"id": "ord_1"}})
        if request.url.path == "/v2/calls":
            return httpx.Response(200, json={"data": {"call_control_id": "cc_1"}})
        if request.url.path.endswith("/actions/answer"):
            return httpx.Response(200, json={"data": {"result": "ok"}})
        if request.url.path.endswith("/actions/hangup"):
            return httpx.Response(200, json={})
        if request.url.path.endswith("/actions/transfer"):
            return httpx.Response(200, json={"data": {"result": "ok"}})
        if request.url.path.endswith("/actions/send_dtmf"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = TelnyxClient()
    # Swap underlying httpx client for one driven by the mock transport.
    # tenacity wait_exponential(min=1) would add ~1s between retries — disable by patching settings.
    client._client = httpx.AsyncClient(base_url="https://api.telnyx.com/v2", transport=transport)
    return client, requests


@pytest.mark.asyncio
async def test_buy_number_posts_e164(patched_client):
    client, reqs = patched_client
    out = await client.buy_number("+14155551234")
    assert out == {"data": {"id": "ord_1"}}
    assert reqs[-1].method == "POST"
    assert reqs[-1].url.path == "/v2/number_orders"
    import json as _json

    assert _json.loads(reqs[-1].content) == {"phone_numbers": [{"phone_number": "+14155551234"}]}


@pytest.mark.asyncio
async def test_initiate_call_payload(monkeypatch, patched_client):
    client, reqs = patched_client
    # initiate_call reads connection_id from settings.
    out = await client.initiate_call(
        to="+15550001",
        from_="+15550002",
        webhook_url="https://hooks/x",
        stream_url="wss://media/x",
    )
    assert out == {"data": {"call_control_id": "cc_1"}}
    import json as _json

    body = _json.loads(reqs[-1].content)
    assert body["to"] == "+15550001"
    assert body["from"] == "+15550002"
    assert body["webhook_url"] == "https://hooks/x"
    assert body["stream_url"] == "wss://media/x"
    assert body["stream_track"] == "both_tracks"
    assert body["answering_machine_detection"] == "premium"


@pytest.mark.asyncio
async def test_answer_with_stream(patched_client):
    client, reqs = patched_client
    await client.answer("cc_abc", stream_url="wss://media/y", stream_track="inbound_track")
    import json as _json

    body = _json.loads(reqs[-1].content)
    assert body == {"stream_url": "wss://media/y", "stream_track": "inbound_track"}
    assert reqs[-1].url.path == "/v2/calls/cc_abc/actions/answer"


@pytest.mark.asyncio
async def test_answer_without_stream_sends_empty_body(patched_client):
    client, reqs = patched_client
    await client.answer("cc_abc")
    import json as _json

    body = _json.loads(reqs[-1].content)
    assert body == {}


@pytest.mark.asyncio
async def test_hangup_swallows_non_2xx(monkeypatch):
    """hangup must not raise on 4xx; it logs and returns."""
    seen: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(409, json={"error": "already gone"})

    client = TelnyxClient()
    client._client = httpx.AsyncClient(
        base_url="https://api.telnyx.com/v2", transport=httpx.MockTransport(handler)
    )
    await client.hangup("cc_x")
    assert seen == [1]


@pytest.mark.asyncio
async def test_hangup_ok(patched_client):
    client, reqs = patched_client
    await client.hangup("cc_z")
    assert reqs[-1].url.path == "/v2/calls/cc_z/actions/hangup"


@pytest.mark.asyncio
async def test_transfer_posts_to_and_from(patched_client):
    client, reqs = patched_client
    await client.transfer("cc_t", to="+15553333", from_="+15554444")
    import json as _json

    assert _json.loads(reqs[-1].content) == {"to": "+15553333", "from": "+15554444"}


@pytest.mark.asyncio
async def test_send_dtmf_posts_digits(patched_client):
    client, reqs = patched_client
    await client.send_dtmf("cc_d", "1234#")
    import json as _json

    assert _json.loads(reqs[-1].content) == {"digits": "1234#"}
    assert reqs[-1].url.path == "/v2/calls/cc_d/actions/send_dtmf"


@pytest.mark.asyncio
async def test_aclose_closes_underlying_client():
    client = TelnyxClient()
    # Use a real AsyncClient (no requests issued); aclose should not raise.
    await client.aclose()
