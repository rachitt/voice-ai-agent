"""kb_lookup builtin tool: registration, dispatch, and auto-binding."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.db import models
from app.routers.web_call_ws import _resolve_tools
from app.tools.builtins import REGISTRY, ToolContext, dispatch


def test_kb_lookup_is_registered():
    assert "kb_lookup" in REGISTRY
    defn = REGISTRY["kb_lookup"]["definition"]
    assert defn["function"]["name"] == "kb_lookup"
    params = defn["function"]["parameters"]["properties"]
    assert "query" in params and "kb_id" in params and "top_k" in params


@pytest.mark.asyncio
async def test_kb_lookup_handler_returns_hits(db_session, monkeypatch):
    from app.kb import store as kb_store

    async def fake_search(*args, **kwargs):
        return [
            kb_store.Retrieval(chunk_id="kbc_1", source_id="kbs_1", text="refunds", score=0.9),
        ]

    monkeypatch.setattr("app.tools.builtins.kb_search" if False else "app.kb.store.search", fake_search)

    org = models.Org(name="O", slug="o")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    call = models.Call(
        org_id=org.id, agent_id=agent.id, direction="web", status="in_progress",
    )
    db_session.add(call)
    await db_session.commit()

    ctx = ToolContext(
        call=call,
        db=db_session,
        args={"query": "what is your refund policy?"},
        knowledge_base_ids=["kb_alpha"],
    )
    result = await dispatch("kb_lookup", ctx)
    assert result["kb_id"] == "kb_alpha"
    assert result["hits"][0]["text"] == "refunds"


@pytest.mark.asyncio
async def test_kb_lookup_missing_query_returns_error(db_session):
    org = models.Org(name="O2", slug="o2")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    call = models.Call(org_id=org.id, agent_id=agent.id, direction="web", status="x")
    db_session.add(call)
    await db_session.commit()
    ctx = ToolContext(call=call, db=db_session, args={"query": ""}, knowledge_base_ids=["kb_a"])
    res = await dispatch("kb_lookup", ctx)
    assert res["error"] == "missing_query"


@pytest.mark.asyncio
async def test_kb_lookup_no_kb_bound(db_session):
    org = models.Org(name="O3", slug="o3")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    call = models.Call(org_id=org.id, agent_id=agent.id, direction="web", status="x")
    db_session.add(call)
    await db_session.commit()
    ctx = ToolContext(call=call, db=db_session, args={"query": "q"}, knowledge_base_ids=[])
    res = await dispatch("kb_lookup", ctx)
    assert res["error"] == "no_kb_bound"


def test_resolve_tools_auto_binds_kb_lookup_for_bound_kb():
    ver = models.AgentVersion(
        agent_id="ag_x", version=1, knowledge_base_ids=["kb_a"], tools=[], flow_graph=None,
    )
    names = [t["function"]["name"] for t in _resolve_tools(ver)]
    assert "kb_lookup" in names


def test_resolve_tools_auto_binds_kb_lookup_for_graph_node():
    graph = {
        "nodes": [{"id": "kb", "data": {"kind": "kb_lookup"}}],
        "edges": [],
    }
    ver = models.AgentVersion(
        agent_id="ag_x", version=1, knowledge_base_ids=[], tools=[], flow_graph=graph,
    )
    names = [t["function"]["name"] for t in _resolve_tools(ver)]
    assert "kb_lookup" in names


def test_resolve_tools_no_kb_when_neither_present():
    ver = models.AgentVersion(
        agent_id="ag_x", version=1, knowledge_base_ids=[], tools=[], flow_graph={"nodes": [], "edges": []},
    )
    names = [t["function"]["name"] for t in _resolve_tools(ver)]
    assert "kb_lookup" not in names


def test_resolve_tools_no_duplicate_when_explicit_and_graph():
    graph = {"nodes": [{"id": "kb", "data": {"kind": "kb_lookup"}}], "edges": []}
    ver = models.AgentVersion(
        agent_id="ag_x",
        version=1,
        knowledge_base_ids=["kb_a"],
        tools=["kb_lookup"],
        flow_graph=graph,
    )
    names = [t["function"]["name"] for t in _resolve_tools(ver)]
    assert names.count("kb_lookup") == 1


# Silence unused-import; keeps mock available for future tests
_ = patch
