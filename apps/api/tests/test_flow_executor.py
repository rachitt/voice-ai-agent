"""Text-mode tests for FlowExecutor — drives a Pipeline through graph states."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.pipeline.flow_executor import FlowExecutor, has_executable_graph
from app.pipeline.orchestrator import (
    AgentConfig,
    Pipeline,
    PipelineEvent,
    TextChunk,
    TurnComplete,
)

# ---------- fixtures ------------------------------------------------------


def text_llm(replies: list[str]):
    """LLM that yields one canned response per turn (FIFO)."""
    state = {"i": 0}

    async def _turn(*, messages, tools):
        i = state["i"]
        state["i"] = i + 1
        text = replies[i] if i < len(replies) else "..."
        for ch in text.split():
            yield TextChunk(text=ch + " ")
        yield TurnComplete(finish_reason="stop")

    return _turn


def classifier_llm(decision: str):
    """LLM that ignores conversational turns and always yields the canned decision."""

    async def _turn(*, messages, tools):
        yield TextChunk(text=decision)
        yield TurnComplete(finish_reason="stop")

    return _turn


def fake_tts():
    async def _tts(text: str) -> AsyncIterator[bytes]:
        for ch in text:
            yield ch.encode("utf-8")

    return _tts


async def drain_until(p: Pipeline, kind: str, timeout: float = 2.0) -> list[PipelineEvent]:
    out: list[PipelineEvent] = []

    async def _drain():
        async for ev in p.events():
            out.append(ev)
            if ev.kind == kind:
                return

    await asyncio.wait_for(_drain(), timeout=timeout)
    return out


# ---------- helpers -------------------------------------------------------


def G(*nodes_and_edges):
    """Tiny helper for terse graph literals.

    Each node is a tuple ('node', id, kind, data?); each edge is
    ('edge', src, tgt, label?).
    """
    nodes, edges = [], []
    for it in nodes_and_edges:
        if it[0] == "node":
            nid, kind = it[1], it[2]
            data = it[3] if len(it) > 3 else {}
            nodes.append({"id": nid, "type": "step", "data": {"kind": kind, **data}})
        elif it[0] == "edge":
            src, tgt = it[1], it[2]
            label = it[3] if len(it) > 3 else None
            edges.append({"id": f"{src}->{tgt}", "source": src, "target": tgt, "label": label})
    return {"nodes": nodes, "edges": edges}


# ---------- has_executable_graph -----------------------------------------


def test_has_executable_graph_false_for_empty():
    assert has_executable_graph(None) is False
    assert has_executable_graph({}) is False
    assert has_executable_graph({"nodes": [], "edges": []}) is False


def test_has_executable_graph_false_without_greeting():
    g = G(("node", "n1", "collect"), ("node", "n2", "end"), ("edge", "n1", "n2"))
    assert has_executable_graph(g) is False


def test_has_executable_graph_true_for_minimal_greeting_to_end():
    g = G(("node", "g", "greeting"), ("node", "e", "end"), ("edge", "g", "e"))
    assert has_executable_graph(g) is True


# ---------- start + greeting → end ---------------------------------------


@pytest.mark.asyncio
async def test_executor_greeting_speaks_node_prompt_and_closes_on_end():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi caller."}),
        ("node", "e", "end"),
        ("edge", "g", "e"),
    )
    cfg = AgentConfig(first_message="WILL_BE_OVERRIDDEN")
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    out: list[PipelineEvent] = []

    async def reader():
        async for ev in pipe.events():
            out.append(ev)

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)

    audio = b"".join(e.audio for e in out if e.audio)
    assert b"Hi caller." in audio
    assert cfg.first_message == "Hi caller."
    # No turn_end fired because pipeline closed before any user turn.
    assert all(e.kind != "turn_end" for e in out)


# ---------- collect node advances on turn_end ----------------------------


@pytest.mark.asyncio
async def test_executor_collect_advances_after_user_turn():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Welcome."}),
        ("node", "c", "collect", {"prompt": "Ask the user for their name."}),
        ("node", "e", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "e"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["Got it."]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    drained: list[PipelineEvent] = []

    async def reader():
        async for ev in pipe.events():
            drained.append(ev)

    reader_task = asyncio.create_task(reader())
    await flow.start()
    # After greeting, executor parked on collect node 'c'.
    assert flow.current_id == "c"

    # Confirm the step prompt got installed.
    assert any(
        isinstance(m.get("content"), str)
        and "Ask the user for their name." in m["content"]
        for m in pipe._messages
    )

    await pipe.feed_user_text("I'm Sam.")
    await asyncio.wait_for(reader_task, timeout=2.0)

    # turn_end should have fired; executor walked to 'e' and closed pipe.
    assert any(e.kind == "turn_end" for e in drained)


# ---------- kb_lookup injects system note --------------------------------


@pytest.mark.asyncio
async def test_executor_kb_lookup_injects_system_note_before_next_collect():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node", "k", "kb_lookup",
            {"kb_id": "kb_x", "query_template": "refunds policy", "top_k": 2},
        ),
        ("node", "c", "collect", {"prompt": "Help with refunds."}),
        ("node", "e", "end"),
        ("edge", "g", "k"),
        ("edge", "k", "c"),
        ("edge", "c", "e"),
    )

    captured: dict = {}

    async def fake_kb(*, kb_id: str, query: str, top_k: int):
        captured["call"] = {"kb_id": kb_id, "query": query, "top_k": top_k}
        return {"hits": [{"text": "Refunds in 3 days.", "score": 0.9}]}

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, kb_dispatch=fake_kb)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    assert flow.current_id == "c"
    assert captured["call"] == {"kb_id": "kb_x", "query": "refunds policy", "top_k": 2}
    assert any(
        m.get("role") == "system" and "Refunds in 3 days." in m.get("content", "")
        for m in pipe._messages
    )

    await pipe.feed_user_text("yes please")
    await asyncio.wait_for(reader_task, timeout=2.0)


# ---------- condition branches on yes/no classifier ----------------------


@pytest.mark.asyncio
async def test_executor_condition_routes_via_yes_label():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "ask", "collect", {"prompt": "Ask if they want a refund."}),
        ("node", "cond", "condition", {"prompt": "User wants a refund?"}),
        ("node", "yes_end", "end", {"title": "refund"}),
        ("node", "no_end", "end", {"title": "no refund"}),
        ("edge", "g", "ask"),
        ("edge", "ask", "cond"),
        ("edge", "cond", "yes_end", "yes"),
        ("edge", "cond", "no_end", "no"),
    )

    cfg = AgentConfig()
    # First turn: conversational. Second invocation: classifier returns 'yes'.
    state = {"n": 0}

    async def llm(*, messages, tools):
        state["n"] += 1
        if state["n"] == 1:
            # conversational turn
            for ch in "Sure.".split():
                yield TextChunk(text=ch)
            yield TurnComplete(finish_reason="stop")
        else:
            yield TextChunk(text="yes")
            yield TurnComplete(finish_reason="stop")

    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    assert flow.current_id == "ask"
    await pipe.feed_user_text("yes please refund")
    await asyncio.wait_for(reader_task, timeout=2.0)
    # Closed via yes_end branch.
    assert flow.current_id == "yes_end"


@pytest.mark.asyncio
async def test_executor_condition_defaults_to_no_when_uncertain():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "ask", "collect", {"prompt": "ask"}),
        ("node", "cond", "condition", {"prompt": "anything?"}),
        ("node", "yes", "end"),
        ("node", "no", "end"),
        ("edge", "g", "ask"),
        ("edge", "ask", "cond"),
        ("edge", "cond", "yes", "yes"),
        ("edge", "cond", "no", "no"),
    )

    cfg = AgentConfig()
    state = {"n": 0}

    async def llm(*, messages, tools):
        state["n"] += 1
        if state["n"] == 1:
            yield TextChunk(text="ok")
            yield TurnComplete(finish_reason="stop")
        else:
            yield TextChunk(text="¯\\_(ツ)_/¯")  # neither yes nor no
            yield TurnComplete(finish_reason="stop")

    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("anything")
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert flow.current_id == "no"


# ---------- voicemail speaks + closes -------------------------------------


@pytest.mark.asyncio
async def test_executor_voicemail_speaks_and_closes():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "v", "voicemail", {"prompt": "Leave message after tone."}),
        ("edge", "g", "v"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    out: list[PipelineEvent] = []

    async def reader():
        async for ev in pipe.events():
            out.append(ev)

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    audio = b"".join(e.audio for e in out if e.audio)
    assert b"Leave message after tone." in audio


# ---------- transfer dispatch ---------------------------------------------


@pytest.mark.asyncio
async def test_executor_transfer_invokes_callback_and_closes():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "t", "transfer", {"webhook": "+15551110000", "prompt": "warm handoff"}),
        ("edge", "g", "t"),
    )
    called: dict = {}

    async def transfer(*, to: str, summary: str = ""):
        called["to"] = to
        called["summary"] = summary

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, transfer=transfer)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert called == {"to": "+15551110000", "summary": "warm handoff"}


# ---------- set_step_prompt replaces prior step prompt -------------------


@pytest.mark.asyncio
async def test_set_step_prompt_replaces_prior_step_prompt():
    cfg = AgentConfig(system_prompt="base")
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    pipe.set_step_prompt("first step")
    pipe.set_step_prompt("second step")
    step_msgs = [
        m for m in pipe._messages
        if m.get("role") == "system" and "second step" in (m.get("content") or "")
    ]
    assert len(step_msgs) == 1
    # The original 'first step' marker is gone.
    assert not any(
        "first step" in (m.get("content") or "") for m in pipe._messages
    )


# ---------- no-root graph is a no-op --------------------------------------


@pytest.mark.asyncio
async def test_executor_renders_template_in_greeting_and_collect():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi {{name}}."}),
        ("node", "c", "collect", {"prompt": "Help {{name}} with {{topic}}."}),
        ("node", "e", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "e"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    vars_bag = {"name": "Sam", "topic": "refunds"}
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables=vars_bag)

    out: list[PipelineEvent] = []

    async def reader():
        async for ev in pipe.events():
            out.append(ev)

    reader_task = asyncio.create_task(reader())
    await flow.start()
    # Collect step prompt rendered immediately (no async event drain needed).
    assert any(
        "Help Sam with refunds." in (m.get("content") or "")
        for m in pipe._messages
    )
    await pipe.feed_user_text("ok")
    await asyncio.wait_for(reader_task, timeout=2.0)
    # After full drain, greeting audio is in the event stream.
    audio = b"".join(e.audio for e in out if e.audio)
    assert b"Hi Sam." in audio


@pytest.mark.asyncio
async def test_executor_renders_kb_query_template():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node", "k", "kb_lookup",
            {"kb_id": "kb_x", "query_template": "refunds for {{order_id}}", "top_k": 1},
        ),
        ("node", "c", "collect", {"prompt": "help"}),
        ("node", "e", "end"),
        ("edge", "g", "k"),
        ("edge", "k", "c"),
        ("edge", "c", "e"),
    )
    seen: dict = {}

    async def fake_kb(*, kb_id, query, top_k):
        seen["query"] = query
        return {"hits": []}

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(
        graph=graph, cfg=cfg, pipe=pipe,
        kb_dispatch=fake_kb, variables={"order_id": "A-42"},
    )

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    assert seen.get("query") == "refunds for A-42"
    await pipe.feed_user_text("ok")
    await asyncio.wait_for(reader_task, timeout=2.0)


def test_render_missing_var_renders_empty():
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(graph={"nodes": [], "edges": []}, cfg=cfg, pipe=pipe, variables={"a": "x"})
    assert flow._render("Hello {{missing}}!") == "Hello !"
    assert flow._render("a={{a}}, b={{b}}") == "a=x, b="


def test_render_supports_dotted_keys():
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(
        graph={"nodes": [], "edges": []}, cfg=cfg, pipe=pipe,
        variables={"customer": {"email": "x@y.com", "tier": "gold"}},
    )
    assert flow._render("{{customer.email}}") == "x@y.com"
    assert flow._render("{{customer.tier}}") == "gold"
    assert flow._render("{{customer.missing}}") == ""


def test_render_non_string_values():
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(
        graph={"nodes": [], "edges": []}, cfg=cfg, pipe=pipe,
        variables={"n": 42, "lst": [1, 2], "obj": {"k": "v"}},
    )
    assert flow._render("n={{n}}") == "n=42"
    assert flow._render("lst={{lst}}") == "lst=[1, 2]"
    assert "k" in flow._render("obj={{obj}}")


@pytest.mark.asyncio
async def test_api_node_merges_response_into_vars(monkeypatch):
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "a", "api", {"webhook": "https://hooks.example/run"}),
        ("node", "c", "collect", {"prompt": "Your account: {{account_id}}"}),
        ("node", "e", "end"),
        ("edge", "g", "a"),
        ("edge", "a", "c"),
        ("edge", "c", "e"),
    )

    class _Resp:
        status_code = 200
        text = '{"account_id": "AC-99", "tier": "gold"}'
        def json(self):
            return {"account_id": "AC-99", "tier": "gold"}

    class _Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, url, json=None):
            return _Resp()

    from app.pipeline import flow_executor as fe
    monkeypatch.setattr(fe.httpx, "AsyncClient", lambda *a, **kw: _Client())

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    vars_bag: dict = {}
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables=vars_bag)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    # Vars merged in place.
    assert vars_bag["account_id"] == "AC-99"
    assert vars_bag["tier"] == "gold"
    # Collect prompt rendered with merged value.
    assert any(
        "Your account: AC-99" in (m.get("content") or "")
        for m in pipe._messages
    )
    await pipe.feed_user_text("ok")
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_executor_no_root_logs_and_returns():
    graph = G(("node", "c", "collect"))  # no greeting → no root
    cfg = AgentConfig(first_message="kept")
    pipe = Pipeline(cfg, llm=text_llm([]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)
    await flow.start()
    # Pipeline never started, no events queued.
    assert pipe.message_count() == 0  # only system prompt would be added; none set here
    # cfg.first_message preserved
    assert cfg.first_message == "kept"
