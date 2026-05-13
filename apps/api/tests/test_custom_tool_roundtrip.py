"""End-to-end custom HTTP tool plumbing: schema resolution + dispatch.

Verifies:
  * a `Tool` DB row resolves to an OpenAI function schema visible to the LLM
  * `_dispatch_http_tool` POSTs LLM args verbatim to `server_url`
  * `X-Voice-Call-Id` header is stamped + user headers are merged
  * non-200, timeout, transport, non-JSON responses degrade gracefully
  * GET method routes args to query params not body

These are the integration seams that caused the "tool defined but never
actually called" bug; if they regress, a calendar/CRM tool silently
no-ops on voice calls.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.db import models
from app.routers import web_call_ws as wcws


def _tool(**overrides) -> models.Tool:
    base = dict(
        id="tool_demo",
        org_id="org_demo",
        name="ping",
        description="say hi",
        server_url="https://example.test/echo",
        method="POST",
        headers={"x-api-key": "secret"},
        params_schema={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        timeout_ms=2000,
    )
    base.update(overrides)
    return models.Tool(**base)


def _patch_httpx(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_cls = wcws.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(wcws.httpx, "AsyncClient", _Factory())


def test_custom_tool_to_openai_lifts_params_schema():
    schema = wcws._custom_tool_to_openai(_tool())
    fn = schema["function"]
    assert schema["type"] == "function"
    assert fn["name"] == "ping"
    assert fn["description"] == "say hi"
    assert fn["parameters"]["required"] == ["msg"]


def test_custom_tool_to_openai_wraps_non_object_schema():
    schema = wcws._custom_tool_to_openai(_tool(params_schema={"foo": "bar"}))
    # No "type" key in input → wrapped into object with properties
    assert schema["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_dispatch_http_post_passes_args_and_headers(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["url"] = str(req.url)
        captured["headers"] = dict(req.headers)
        captured["body"] = req.content.decode()
        return httpx.Response(200, json={"echoed": "hi", "request_id": "rid_1"})

    _patch_httpx(monkeypatch, handler)
    out = await wcws._dispatch_http_tool(
        _tool(), {"msg": "hi"}, call_id="call_xyz"
    )
    assert out == {"ok": True, "result": {"echoed": "hi", "request_id": "rid_1"}}
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.test/echo"
    assert captured["headers"]["x-api-key"] == "secret"
    assert captured["headers"]["x-voice-call-id"] == "call_xyz"
    assert '"msg":"hi"' in captured["body"].replace(" ", "")


@pytest.mark.asyncio
async def test_dispatch_http_get_routes_args_to_query(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["url"] = str(req.url)
        captured["body"] = req.content
        return httpx.Response(200, json={"ok": 1})

    _patch_httpx(monkeypatch, handler)
    await wcws._dispatch_http_tool(
        _tool(method="GET"), {"q": "weather"}, call_id="call_q"
    )
    assert captured["method"] == "GET"
    assert "q=weather" in captured["url"]
    assert captured["body"] == b""


@pytest.mark.asyncio
async def test_dispatch_http_non_200_returns_error_payload(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"err": "down"})

    _patch_httpx(monkeypatch, handler)
    out = await wcws._dispatch_http_tool(_tool(), {"msg": "x"}, call_id="c1")
    assert out["error"] == "http_error"
    assert out["status"] == 503
    assert out["body"] == {"err": "down"}


@pytest.mark.asyncio
async def test_dispatch_http_non_json_body_truncated(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="x" * 5000, headers={"content-type": "text/plain"})

    _patch_httpx(monkeypatch, handler)
    out = await wcws._dispatch_http_tool(_tool(), {"msg": "x"}, call_id="c1")
    assert out["error"] == "http_error"
    assert isinstance(out["body"], str)
    assert len(out["body"]) == 2000


@pytest.mark.asyncio
async def test_dispatch_http_timeout_returns_typed_error(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow upstream")

    _patch_httpx(monkeypatch, handler)
    out = await wcws._dispatch_http_tool(_tool(timeout_ms=500), {"m": "x"}, call_id="c1")
    assert out == {"error": "timeout", "timeout_s": 0.5}


@pytest.mark.asyncio
async def test_dispatch_http_transport_error_returns_typed_error(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    _patch_httpx(monkeypatch, handler)
    out = await wcws._dispatch_http_tool(_tool(), {"m": "x"}, call_id="c1")
    assert out["error"] == "transport_error"
    assert "dns fail" in out["detail"]


@pytest.mark.asyncio
async def test_resolve_tools_loads_custom_row_from_db(db_session):
    org = models.Org(id="org_rt", name="rt", slug="rt")
    db_session.add(org)
    tool = _tool(org_id=org.id)
    db_session.add(tool)
    await db_session.commit()

    ver = models.AgentVersion(
        agent_id="ag_x",
        version=1,
        tools=[tool.id],
        knowledge_base_ids=[],
    )
    defs, custom = await wcws._resolve_tools(ver, db=db_session, org_id=org.id)
    names = [t["function"]["name"] for t in defs]
    assert "ping" in names
    assert "ping" in custom
    assert custom["ping"].server_url == "https://example.test/echo"


@pytest.mark.asyncio
async def test_resolve_tools_mixed_builtin_and_custom(db_session):
    org = models.Org(id="org_mix", name="mix", slug="mix")
    db_session.add(org)
    tool = _tool(org_id=org.id, name="lookup_acct")
    db_session.add(tool)
    await db_session.commit()

    ver = models.AgentVersion(
        agent_id="ag_x",
        version=1,
        tools=["end_call", tool.id],
        knowledge_base_ids=[],
    )
    defs, custom = await wcws._resolve_tools(ver, db=db_session, org_id=org.id)
    names = [t["function"]["name"] for t in defs]
    assert "end_call" in names
    assert "lookup_acct" in names
    assert custom["lookup_acct"].id == tool.id


@pytest.mark.asyncio
async def test_resolve_tools_wrong_org_silently_drops_custom_ref(db_session):
    org_a = models.Org(id="org_a", name="a", slug="a")
    org_b = models.Org(id="org_b", name="b", slug="b")
    db_session.add_all([org_a, org_b])
    tool = _tool(org_id=org_b.id)
    db_session.add(tool)
    await db_session.commit()

    # Agent in org_a references tool that belongs to org_b — must NOT leak.
    ver = models.AgentVersion(
        agent_id="ag_x",
        version=1,
        tools=[tool.id],
        knowledge_base_ids=[],
    )
    defs, custom = await wcws._resolve_tools(ver, db=db_session, org_id=org_a.id)
    assert defs == []
    assert custom == {}
