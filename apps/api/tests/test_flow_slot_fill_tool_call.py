"""slot_fill, tool_call, NL transitions, per-node tools — runtime coverage.

These match Retell Conversation Flow / Vapi Workflow semantics:
  * slot_fill loops in place until every required slot lands in the var bag
  * tool_call fires the bound tool, branches success/error, speaks lifecycle msgs
  * per-node tools override what the LLM sees at each step
  * NL conditions on outbound edges route by classifier on the latest turn
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.pipeline.flow_executor import FlowExecutor
from app.pipeline.orchestrator import (
    AgentConfig,
    Pipeline,
    PipelineEvent,
    TextChunk,
    ToolCall,
    TurnComplete,
)

# ---------- helpers --------------------------------------------------------


def text_llm(replies: list[str]):
    state = {"i": 0}

    async def _turn(*, messages, tools):
        i = state["i"]
        state["i"] = i + 1
        text = replies[i] if i < len(replies) else "ok"
        for ch in text.split():
            yield TextChunk(text=ch + " ")
        yield TurnComplete(finish_reason="stop")

    return _turn


def fake_tts():
    async def _tts(text: str) -> AsyncIterator[bytes]:
        for ch in text:
            yield ch.encode("utf-8")

    return _tts


def G(*items):
    nodes, edges = [], []
    for it in items:
        if it[0] == "node":
            nid, kind = it[1], it[2]
            data = it[3] if len(it) > 3 else {}
            nodes.append({"id": nid, "type": "step", "data": {"kind": kind, **data}})
        else:  # edge
            src, tgt = it[1], it[2]
            label = it[3] if len(it) > 3 else None
            ed_data = it[4] if len(it) > 4 else None
            ed: dict = {"id": f"{src}->{tgt}{label or ''}", "source": src, "target": tgt}
            if label is not None:
                ed["label"] = label
            if ed_data is not None:
                ed["data"] = ed_data
            edges.append(ed)
    return {"nodes": nodes, "edges": edges}


# ---------- slot_fill ------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_fill_loops_until_all_required_in_var_bag():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "s",
            "slot_fill",
            {
                "prompt": "Book a demo.",
                "slots": [
                    {"name": "attendee_email", "prompt": "their email", "required": True},
                    {"name": "start_iso", "prompt": "when", "required": True},
                ],
            },
        ),
        ("node", "e", "end"),
        ("edge", "g", "s"),
        ("edge", "s", "e"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok", "ok"]), tts=fake_tts())
    vars_bag: dict = {}
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables=vars_bag)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    assert flow.current_id == "s"

    # Turn 1: user supplies email. Slot bag empty → still missing one.
    vars_bag["attendee_email"] = "alice@example.com"
    await pipe.feed_user_text("alice at example dot com")
    await asyncio.sleep(0.05)
    assert flow.current_id == "s"  # still parked

    # Turn 2: user supplies the time → all slots filled → advances.
    vars_bag["start_iso"] = "2026-05-15T17:00:00Z"
    await pipe.feed_user_text("tomorrow at 5")
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_slot_fill_auto_binds_extract_data_tool():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "s",
            "slot_fill",
            {"slots": [{"name": "topic", "required": True}]},
        ),
        ("node", "e", "end"),
        ("edge", "g", "s"),
        ("edge", "s", "e"),
    )
    # Agent declared NO tools. slot_fill must auto-bind extract_data anyway.
    cfg = AgentConfig(tools=[])
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    asyncio.create_task(reader())
    await flow.start()
    names = {t["function"]["name"] for t in cfg.tools}
    assert "extract_data" in names


@pytest.mark.asyncio
async def test_slot_fill_skips_when_already_satisfied():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "s",
            "slot_fill",
            {"slots": [{"name": "name", "required": True}]},
        ),
        ("node", "e", "end"),
        ("edge", "g", "s"),
        ("edge", "s", "e"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables={"name": "Sam"})

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)


# ---------- tool_call ------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_fires_dispatch_and_routes_success():
    dispatched: list[ToolCall] = []

    async def dispatch(tc: ToolCall) -> dict:
        dispatched.append(tc)
        return {"event_id": "evt_1", "html_link": "https://cal/evt_1"}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {
                "tool": "book_meeting",
                "arg_map": {"title": "topic", "start_iso": "when"},
                "pre_message": "Booking now.",
                "success_message": "Done!",
            },
        ),
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(
        graph=graph,
        cfg=cfg,
        pipe=pipe,
        variables={"topic": "Demo with Alice", "when": "2026-05-15T17:00:00Z"},
    )

    drained: list[PipelineEvent] = []

    async def reader():
        async for ev in pipe.events():
            drained.append(ev)

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)

    assert len(dispatched) == 1
    assert dispatched[0].name == "book_meeting"
    assert dispatched[0].arguments == {
        "title": "Demo with Alice",
        "start_iso": "2026-05-15T17:00:00Z",
    }
    # tool_result event surfaced for UI.
    assert any(e.kind == "tool_result" and e.text == "book_meeting" for e in drained)


@pytest.mark.asyncio
async def test_tool_call_error_routes_to_error_branch():
    async def dispatch(_tc: ToolCall) -> dict:
        return {"error": "calendar_unconfigured"}

    transferred: list[str] = []

    async def transfer(*, to: str, summary: str = "") -> None:
        transferred.append(to)

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {"tool": "book_meeting", "error_message": "Sorry, can't book."},
        ),
        ("node", "ok", "end"),
        (
            "node",
            "ko",
            "transfer",
            {"webhook": "+15550000000", "prompt": "Caller wants human."},
        ),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, transfer=transfer)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    # Error branch took the transfer route, not success.
    assert transferred == ["+15550000000"]


@pytest.mark.asyncio
async def test_tool_call_no_dispatch_returns_typed_error():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "t", "tool_call", {"tool": "book_meeting"}),
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )
    cfg = AgentConfig()
    # NO tool_dispatch wired.
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    # Result on var bag carries the error, so downstream nodes can read it.
    assert flow._vars.get("book_meeting") == {"error": "no_tool_dispatch"}


# ---------- NL transition classifier ---------------------------------------


@pytest.mark.asyncio
async def test_collect_nl_transition_picks_matching_branch():
    """Multi-edge `collect` routed by NL classifier on edge.data.condition."""
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Want a demo or pricing?"}),
        ("node", "demo", "end"),
        ("node", "price", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "demo", None, {"condition": "User wants a product demo"}),
        ("edge", "c", "price", None, {"condition": "User wants pricing details"}),
    )

    classified: dict = {}

    async def classifier(*, messages, tools):
        # First call: greeting LLM. Subsequent call: classifier. Distinguish by
        # the system prompt content.
        sys = (messages[0] or {}).get("content", "") if messages else ""
        if "branches" in sys.lower():
            classified["fired"] = True
            yield TextChunk(text="2")  # → price branch
        else:
            yield TextChunk(text="hi")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=classifier, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    assert flow.current_id == "c"

    await pipe.feed_user_text("I want pricing.")
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert classified.get("fired") is True


@pytest.mark.asyncio
async def test_collect_single_outbound_no_classifier_call():
    """Single outbound edge → don't invoke classifier."""
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Anything?"}),
        ("node", "e", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "e"),  # no condition
    )

    calls: dict = {"n": 0}

    async def llm(*, messages, tools):
        calls["n"] += 1
        yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    n_before = calls["n"]
    await pipe.feed_user_text("yeah")
    await asyncio.wait_for(reader_task, timeout=2.0)
    # Exactly one user turn → exactly one extra LLM call (no classifier).
    assert calls["n"] == n_before + 1


# ---------- per-node tools override ----------------------------------------


@pytest.mark.asyncio
async def test_tool_call_dispatch_raises_routes_to_error():
    """Tool dispatcher raises → typed error result + error branch."""

    async def dispatch(_tc: ToolCall) -> dict:
        raise RuntimeError("upstream 500")

    err_branch_taken: dict = {"hit": False}

    transferred: list[str] = []

    async def transfer(*, to: str, summary: str = "") -> None:
        transferred.append(to)
        err_branch_taken["hit"] = True

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {"tool": "book_meeting", "error_message": "Boom."},
        ),
        ("node", "ok", "end"),
        ("node", "ko", "transfer", {"webhook": "+15550000000", "prompt": "human"}),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, transfer=transfer)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert err_branch_taken["hit"] is True
    assert isinstance(flow._vars.get("t"), dict)
    assert flow._vars["t"].get("error") == "tool_failed"


@pytest.mark.asyncio
async def test_tool_call_unlabeled_outbound_terminates_when_missing():
    """No labelled branch + no fallback edge → executor terminates."""

    async def dispatch(_tc: ToolCall) -> dict:
        return {"event_id": "evt_1"}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "t", "tool_call", {"tool": "book_meeting"}),
        # No outbound from t at all
        ("edge", "g", "t"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    # Pipeline closed (terminate called).
    assert pipe._closed


@pytest.mark.asyncio
async def test_nl_classifier_unparsable_response_falls_back_to_first(monkeypatch):
    """Classifier returns garbage → executor falls back to first outbound."""
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Q?"}),
        ("node", "a", "end"),
        ("node", "b", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "a", None, {"condition": "alpha"}),
        ("edge", "c", "b", None, {"condition": "beta"}),
    )

    async def llm(*, messages, tools):
        sys = (messages[0] or {}).get("content", "") if messages else ""
        if "branches" in sys.lower():
            yield TextChunk(text="i'm not sure")  # no digit
        else:
            yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("anything")
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_nl_classifier_out_of_range_picks_first():
    """LLM picks 99 → out-of-range → fall back to first outbound."""
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Q?"}),
        ("node", "a", "end"),
        ("node", "b", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "a", None, {"condition": "alpha"}),
        ("edge", "c", "b", None, {"condition": "beta"}),
    )

    async def llm(*, messages, tools):
        sys = (messages[0] or {}).get("content", "") if messages else ""
        if "branches" in sys.lower():
            yield TextChunk(text="99")
        else:
            yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("yo")
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_nl_classifier_llm_raises_returns_none():
    """LLM crashes mid-classify → executor falls back to first outbound."""
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Q?"}),
        ("node", "a", "end"),
        ("node", "b", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "a", None, {"condition": "alpha"}),
        ("edge", "c", "b", None, {"condition": "beta"}),
    )

    async def llm(*, messages, tools):
        sys = (messages[0] or {}).get("content", "") if messages else ""
        if "branches" in sys.lower():
            raise RuntimeError("upstream timeout")
        yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("yo")
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_confirm_classifier_llm_error_treated_as_no():
    """Confirm-classifier crashes → safe default: not approved."""
    fired: dict = {"n": 0}

    async def dispatch(_tc: ToolCall) -> dict:
        fired["n"] += 1
        return {"ok": True}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {"tool": "book_meeting", "confirm_before_fire": True},
        ),
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )

    async def llm(*, messages, tools):
        if "confirm" in (messages[0] or {}).get("content", "").lower():
            raise RuntimeError("nope")
        yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("uhh")
    await asyncio.sleep(0.05)
    # Dispatch must NOT have fired — classifier crashed → treated as no.
    assert fired["n"] == 0


@pytest.mark.asyncio
async def test_per_node_tools_filters_agent_tools_in_place():
    """A node with `tools=["book_meeting"]` must not expose the agent's other
    tools to the LLM while it's active."""
    book = {
        "type": "function",
        "function": {"name": "book_meeting", "parameters": {"type": "object"}},
    }
    transfer = {
        "type": "function",
        "function": {"name": "transfer_call", "parameters": {"type": "object"}},
    }

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c", "collect", {"prompt": "Q?", "tools": ["book_meeting"]}),
        ("node", "e", "end"),
        ("edge", "g", "c"),
        ("edge", "c", "e"),
    )
    cfg = AgentConfig(tools=[book, transfer])
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    asyncio.create_task(reader())
    await flow.start()
    assert flow.current_id == "c"
    names = {t["function"]["name"] for t in cfg.tools}
    assert names == {"book_meeting"}


@pytest.mark.asyncio
async def test_tool_call_confirm_flow_user_says_yes(monkeypatch):
    fired: dict = {"n": 0}

    async def dispatch(_tc: ToolCall) -> dict:
        fired["n"] += 1
        return {"event_id": "evt_ok"}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {
                "tool": "book_meeting",
                "confirm_before_fire": True,
                "confirm_message": "Should I book at {{when}}?",
                "success_message": "Booked.",
            },
        ),
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )

    async def llm(*, messages, tools):
        sys = (messages[0] or {}).get("content", "") if messages else ""
        if "confirm" in sys.lower():
            yield TextChunk(text="yes")
        else:
            yield TextChunk(text="ok")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables={"when": "5pm"})

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    # Awaiting confirmation now.
    assert flow._pending_confirm.get("t") is True
    await pipe.feed_user_text("yes please")
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert fired["n"] == 1


@pytest.mark.asyncio
async def test_tool_call_confirm_flow_user_says_no_stays_parked():
    fired: dict = {"n": 0}

    async def dispatch(_tc: ToolCall) -> dict:
        fired["n"] += 1
        return {"ok": True}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        (
            "node",
            "t",
            "tool_call",
            {
                "tool": "book_meeting",
                "confirm_before_fire": True,
                "retry_prompt": "Which detail to change?",
            },
        ),
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )

    async def llm(*, messages, tools):
        yield TextChunk(text="no")
        yield TurnComplete(finish_reason="stop")

    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=llm, tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    asyncio.create_task(reader())
    await flow.start()
    await pipe.feed_user_text("hm not sure")
    await asyncio.sleep(0.05)
    # Tool did NOT fire; node still active waiting on more clarification.
    assert fired["n"] == 0
    assert flow.current_id == "t"


@pytest.mark.asyncio
async def test_tool_call_missing_tool_ref_falls_through():
    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "t", "tool_call", {}),  # no `tool` key
        ("node", "e", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "e"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)


@pytest.mark.asyncio
async def test_tool_call_default_arg_map_copies_var_bag():
    captured: dict = {}

    async def dispatch(tc: ToolCall) -> dict:
        captured["args"] = tc.arguments
        return {"ok": True}

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "t", "tool_call", {"tool": "book_meeting"}),  # no arg_map
        ("node", "ok", "end"),
        ("node", "ko", "end"),
        ("edge", "g", "t"),
        ("edge", "t", "ok", "success"),
        ("edge", "t", "ko", "error"),
    )
    cfg = AgentConfig()
    pipe = Pipeline(cfg, llm=text_llm(["ok"]), tts=fake_tts(), tool_dispatch=dispatch)
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe, variables={"title": "X", "start_iso": "Y"})

    async def reader():
        async for _ in pipe.events():
            pass

    reader_task = asyncio.create_task(reader())
    await flow.start()
    await asyncio.wait_for(reader_task, timeout=2.0)
    assert captured["args"] == {"title": "X", "start_iso": "Y"}


@pytest.mark.asyncio
async def test_per_node_tools_restored_to_base_on_unconfigured_node():
    """A node without `tools` restores the full agent tool set."""
    book = {
        "type": "function",
        "function": {"name": "book_meeting", "parameters": {"type": "object"}},
    }
    transfer = {
        "type": "function",
        "function": {"name": "transfer_call", "parameters": {"type": "object"}},
    }

    graph = G(
        ("node", "g", "greeting", {"prompt": "Hi."}),
        ("node", "c1", "collect", {"prompt": "Q?", "tools": ["book_meeting"]}),
        ("node", "c2", "collect", {"prompt": "Q2?"}),  # no override
        ("node", "e", "end"),
        ("edge", "g", "c1"),
        ("edge", "c1", "c2"),
        ("edge", "c2", "e"),
    )
    cfg = AgentConfig(tools=[book, transfer])
    pipe = Pipeline(cfg, llm=text_llm(["ok", "ok"]), tts=fake_tts())
    flow = FlowExecutor(graph=graph, cfg=cfg, pipe=pipe)

    async def reader():
        async for _ in pipe.events():
            pass

    asyncio.create_task(reader())
    await flow.start()
    # On c1 the set is narrowed to book_meeting.
    assert {t["function"]["name"] for t in cfg.tools} == {"book_meeting"}

    await pipe.feed_user_text("ok")
    await asyncio.sleep(0.05)
    # After advancing to c2, the full set is back.
    assert {t["function"]["name"] for t in cfg.tools} == {"book_meeting", "transfer_call"}
