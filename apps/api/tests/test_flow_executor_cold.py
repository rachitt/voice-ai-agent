"""flow_executor cold paths: parser tolerance + helper functions + skip branches."""

from __future__ import annotations

from typing import Any

import pytest

from app.pipeline.flow_executor import (
    FlowExecutor,
    _format_kb_for_prompt,
    _safe_dumps,
    has_executable_graph,
)
from app.pipeline.orchestrator import AgentConfig, Pipeline


def _mk_pipe() -> Pipeline:
    return Pipeline(AgentConfig(first_message=None, system_prompt=""))


def test_constructor_skips_non_dict_nodes_and_edges():
    """Malformed graphs shouldn't blow up the FlowExecutor."""
    fe = FlowExecutor(
        graph={
            "nodes": [
                "string-not-dict",  # skipped (non-dict)
                {"id": "ok", "data": {"kind": "greeting"}},
                {"id": "no-kind"},  # missing kind → skipped
                {"data": {"kind": "end"}},  # missing id → skipped
            ],
            "edges": [
                "string-not-dict",  # skipped
                {"target": "ok"},  # missing source → skipped
                {"source": "ok"},  # missing target → skipped
                {"source": "ok", "target": "ok"},  # OK
            ],
        },
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        variables={},
    )
    assert "ok" in fe._nodes
    assert "no-kind" not in fe._nodes
    assert fe._edges.get("ok") == [("ok", None)]


def test_render_empty_text_returns_empty():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    assert fe._render("") == ""
    assert fe._render(None) == ""


def test_render_handles_dict_and_list_vars():
    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        variables={"obj": {"k": 1}, "lst": [1, 2], "num": 42},
    )
    assert fe._render("{{obj}}") == '{"k": 1}'
    assert fe._render("{{lst}}") == "[1, 2]"
    assert fe._render("{{num}}") == "42"


def test_render_falls_back_to_str_on_non_serializable():
    class _Bad:
        def __repr__(self):
            return "<bad>"

    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        variables={"x": _Bad()},
    )
    assert fe._render("{{x}}") == "<bad>"


def test_lookup_var_dotted_into_non_dict_returns_none():
    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        variables={"name": "ada"},  # name is a string
    )
    assert fe._lookup_var("name.first") is None


def test_format_kb_returns_empty_for_non_dict():
    assert _format_kb_for_prompt(None) == ""
    assert _format_kb_for_prompt("not a dict") == ""
    assert _format_kb_for_prompt({"hits": "wrong-type"}) == ""
    assert _format_kb_for_prompt({"hits": []}) == ""


def test_format_kb_skips_bad_hits():
    out = _format_kb_for_prompt(
        {
            "hits": [
                "not a dict",  # skipped
                {"text": ""},  # empty body skipped
                {"text": "real content"},
            ]
        }
    )
    assert "real content" in out


def test_format_kb_truncates_long_bodies():
    body = "x" * 1000
    out = _format_kb_for_prompt({"hits": [{"text": body}]})
    assert "[1]" in out and len(out) < 1000


def test_safe_dumps_falls_back_to_repr():
    class _NotJson:
        def __repr__(self):
            return "<weird>"

    assert _safe_dumps(_NotJson()) == "<weird>"
    assert _safe_dumps({"a": 1}) == '{"a": 1}'


def test_has_executable_graph_rejects_non_list_nodes():
    assert has_executable_graph({"nodes": "not-list", "edges": []}) is False
    assert has_executable_graph({"nodes": [], "edges": "not-list"}) is False


def test_has_executable_graph_skips_non_dict_node():
    assert (
        has_executable_graph(
            {"nodes": ["string", {"id": "g", "data": {"kind": "greeting"}}], "edges": [{}]}
        )
        is True
    )


@pytest.mark.asyncio
async def test_kb_node_skip_when_no_dispatch_fn():
    """kb_lookup node should no-op when executor was built without a kb_dispatch."""
    fe = FlowExecutor(
        graph={
            "nodes": [
                {"id": "g", "data": {"kind": "greeting", "prompt": "hi"}},
                {"id": "kb", "data": {"kind": "kb_lookup", "query_template": "q"}},
                {"id": "e", "data": {"kind": "end"}},
            ],
            "edges": [
                {"source": "g", "target": "kb"},
                {"source": "kb", "target": "e"},
            ],
        },
        cfg=AgentConfig(knowledge_base_ids=["kb_1"]),
        pipe=_mk_pipe(),
    )
    # _do_kb returns silently because self._kb is None.
    nv = fe._nodes["kb"]
    await fe._do_kb(nv)


@pytest.mark.asyncio
async def test_kb_node_skip_when_no_query_or_kb():
    """Both missing kb_id and missing query log skip + return."""
    calls: list[Any] = []

    async def fake_dispatch(**kw):
        calls.append(kw)
        return {"hits": []}

    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(knowledge_base_ids=[]),
        pipe=_mk_pipe(),
        kb_dispatch=fake_dispatch,
    )
    from app.pipeline.flow_executor import _NodeView

    # Empty query → skip.
    await fe._do_kb(_NodeView(id="x", kind="kb_lookup", data={"kb_id": "k", "query_template": ""}))
    # Empty kb_id → skip.
    await fe._do_kb(
        _NodeView(id="y", kind="kb_lookup", data={"query_template": "q"})
    )
    assert calls == []


@pytest.mark.asyncio
async def test_kb_node_swallows_dispatch_error():
    async def boom(**kw):
        raise RuntimeError("kb 500")

    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(knowledge_base_ids=["kb_1"]),
        pipe=_mk_pipe(),
        kb_dispatch=boom,
    )
    from app.pipeline.flow_executor import _NodeView

    # Should not raise.
    await fe._do_kb(_NodeView(id="x", kind="kb_lookup", data={"query_template": "q"}))


@pytest.mark.asyncio
async def test_api_node_no_url_returns_silently():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    from app.pipeline.flow_executor import _NodeView

    await fe._do_api(_NodeView(id="x", kind="api", data={"webhook": ""}))


@pytest.mark.asyncio
async def test_api_node_swallows_network_error(monkeypatch):
    """When the upstream raises, the executor logs and continues."""
    import httpx

    from app.pipeline import flow_executor as fe_mod

    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    from app.pipeline.flow_executor import _NodeView

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    transport = httpx.MockTransport(handler)
    real_cls = fe_mod.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(fe_mod.httpx, "AsyncClient", _Factory())
    await fe._do_api(_NodeView(id="x", kind="api", data={"webhook": "https://up/api"}))


@pytest.mark.asyncio
async def test_api_node_non_json_response_still_logs_note(monkeypatch):
    import httpx

    from app.pipeline import flow_executor as fe_mod

    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    from app.pipeline.flow_executor import _NodeView

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="plain text body")

    transport = httpx.MockTransport(handler)
    real_cls = fe_mod.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(fe_mod.httpx, "AsyncClient", _Factory())
    await fe._do_api(_NodeView(id="x", kind="api", data={"webhook": "https://up/api", "title": "t"}))


@pytest.mark.asyncio
async def test_transfer_node_skip_no_dispatch_fn():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    from app.pipeline.flow_executor import _NodeView

    # _transfer is None → log + return.
    await fe._do_transfer(_NodeView(id="x", kind="transfer", data={"webhook": "+15551234"}))


@pytest.mark.asyncio
async def test_transfer_node_skip_when_no_target():
    calls: list[dict] = []

    async def fake_transfer(*, to: str, summary: str = "") -> None:
        calls.append({"to": to, "summary": summary})

    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        transfer=fake_transfer,
    )
    from app.pipeline.flow_executor import _NodeView

    await fe._do_transfer(_NodeView(id="x", kind="transfer", data={"webhook": ""}))
    assert calls == []


@pytest.mark.asyncio
async def test_transfer_node_swallows_dispatch_error():
    async def boom(*, to: str, summary: str = "") -> None:
        raise RuntimeError("telnyx fail")

    fe = FlowExecutor(
        graph={"nodes": [], "edges": []},
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
        transfer=boom,
    )
    from app.pipeline.flow_executor import _NodeView

    await fe._do_transfer(_NodeView(id="x", kind="transfer", data={"webhook": "+15551234"}))


@pytest.mark.asyncio
async def test_enter_unknown_node_logs_and_returns():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    await fe._enter("does_not_exist")
    assert fe.current_id is None  # never updated


@pytest.mark.asyncio
async def test_enter_unhandled_kind_falls_through_via_enter_after():
    """An unknown kind logs `flow.unhandled_kind` then attempts _enter_after."""
    fe = FlowExecutor(
        graph={
            "nodes": [
                {"id": "x", "data": {"kind": "mystery"}},
                {"id": "e", "data": {"kind": "end"}},
            ],
            "edges": [{"source": "x", "target": "e"}],
        },
        cfg=AgentConfig(),
        pipe=_mk_pipe(),
    )
    await fe._enter("x")
    # `end` triggers _terminate which marks _closed
    assert fe._closed is True


@pytest.mark.asyncio
async def test_terminate_idempotent():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    await fe._terminate()
    await fe._terminate()  # second call is no-op


@pytest.mark.asyncio
async def test_on_turn_end_noop_when_closed():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    fe._closed = True
    await fe._on_turn_end()


@pytest.mark.asyncio
async def test_on_turn_end_noop_when_current_id_none():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    fe.current_id = None
    await fe._on_turn_end()


@pytest.mark.asyncio
async def test_on_turn_end_noop_when_current_node_missing():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    fe.current_id = "stale"  # not in self._nodes
    await fe._on_turn_end()


@pytest.mark.asyncio
async def test_enter_after_returns_when_no_outbound():
    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_mk_pipe())
    await fe._enter_after("orphan")  # no edges from this node


@pytest.mark.asyncio
async def test_classify_returns_no_on_llm_exception():
    """When the inline classifier LLM raises, return 'no' safely."""

    class _BadPipe:
        _messages: list[dict] = [{"role": "user", "content": "I want a refund"}]

        async def _llm(self, **kw):
            raise RuntimeError("provider down")
            yield  # pragma: no cover - never reached

    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_BadPipe())  # type: ignore[arg-type]
    from app.pipeline.flow_executor import _NodeView

    out = await fe._classify(_NodeView(id="c", kind="condition", data={"prompt": "refund?"}))
    assert out == "no"


@pytest.mark.asyncio
async def test_classify_explicit_no_starts_with_no():
    """Explicit 'no, the caller…' should still classify as no."""
    from app.pipeline.orchestrator import TextChunk, TurnComplete, ToolCall  # noqa: F401

    class _FakePipe:
        _messages: list[dict] = [{"role": "user", "content": "I want pizza"}]

        async def _llm(self, **kw):
            yield TextChunk(text="no — caller off-topic")
            yield ToolCall(id="tc", name="x", arguments={})
            yield TurnComplete()

    fe = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=AgentConfig(), pipe=_FakePipe())  # type: ignore[arg-type]
    from app.pipeline.flow_executor import _NodeView

    out = await fe._classify(_NodeView(id="c", kind="condition", data={"prompt": "refund?"}))
    assert out == "no"
