"""Server-side flow_graph validator + publish gate."""

from __future__ import annotations

import pytest

from app.schemas.flow_graph_validators import validate_flow_graph


def _node(nid: str, kind: str) -> dict:
    return {"id": nid, "data": {"kind": kind}, "position": {"x": 0, "y": 0}}


def _edge(src: str, tgt: str, label: str | None = None) -> dict:
    e = {"id": f"{src}->{tgt}", "source": src, "target": tgt}
    if label is not None:
        e["label"] = label
    return e


def test_validator_accepts_linear_graph():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("c", "collect"),
            _node("a", "api"),
            _node("end", "end"),
        ],
        "edges": [_edge("g", "c"), _edge("c", "a"), _edge("a", "end")],
    }
    res = validate_flow_graph(graph)
    assert res.ok, res.errors
    assert not res.warnings


def test_validator_accepts_kb_lookup_node():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("kb", "kb_lookup"),
            _node("end", "end"),
        ],
        "edges": [_edge("g", "kb"), _edge("kb", "end")],
    }
    res = validate_flow_graph(graph)
    assert res.ok, res.errors


def test_validator_rejects_kb_lookup_with_two_outbound():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("kb", "kb_lookup"),
            _node("a", "end"),
            _node("b", "end"),
        ],
        "edges": [_edge("g", "kb"), _edge("kb", "a"), _edge("kb", "b")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("outbound" in e and "kb_lookup" in e for e in res.errors)


def test_validator_rejects_missing_greeting():
    graph = {"nodes": [_node("c", "collect"), _node("end", "end")], "edges": [_edge("c", "end")]}
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("greeting" in e for e in res.errors)


def test_validator_rejects_two_greetings():
    graph = {
        "nodes": [_node("g1", "greeting"), _node("g2", "greeting"), _node("end", "end")],
        "edges": [_edge("g1", "end"), _edge("g2", "end")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("exactly one greeting" in e for e in res.errors)


def test_validator_rejects_self_loop():
    graph = {
        "nodes": [_node("g", "greeting"), _node("c", "collect"), _node("end", "end")],
        "edges": [_edge("g", "c"), _edge("c", "c"), _edge("c", "end")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("self-loop" in e for e in res.errors)


def test_validator_rejects_outbound_from_terminal():
    graph = {
        "nodes": [_node("g", "greeting"), _node("end", "end"), _node("c", "collect")],
        "edges": [_edge("g", "end"), _edge("end", "c")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("end cannot have outbound" in e for e in res.errors)


def test_validator_rejects_inbound_to_greeting():
    graph = {
        "nodes": [_node("g", "greeting"), _node("c", "collect"), _node("end", "end")],
        "edges": [_edge("g", "c"), _edge("c", "g"), _edge("c", "end")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("greeting cannot receive inbound" in e for e in res.errors)


def test_validator_rejects_extra_outbound_on_linear_node():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("c", "collect"),
            _node("a", "api"),
            _node("end", "end"),
        ],
        "edges": [_edge("g", "c"), _edge("g", "a"), _edge("c", "end")],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    # greeting outMax=1 → second outbound rejected at edge validation
    assert any("greeting cannot" in e or "outbound" in e for e in res.errors)


def test_validator_accepts_condition_with_two_labeled_branches():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("cond", "condition"),
            _node("a", "api"),
            _node("vm", "voicemail"),
        ],
        "edges": [
            _edge("g", "cond"),
            _edge("cond", "a", "yes"),
            _edge("cond", "vm", "no"),
        ],
    }
    res = validate_flow_graph(graph)
    assert res.ok, res.errors


def test_validator_rejects_condition_unlabeled():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("cond", "condition"),
            _node("a", "api"),
            _node("vm", "voicemail"),
        ],
        "edges": [
            _edge("g", "cond"),
            _edge("cond", "a"),  # no label
            _edge("cond", "vm", "no"),
        ],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("missing label" in e for e in res.errors)


def test_validator_rejects_condition_three_branches():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("cond", "condition"),
            _node("a", "api"),
            _node("b", "api"),
            _node("vm", "voicemail"),
        ],
        "edges": [
            _edge("g", "cond"),
            _edge("cond", "a", "yes"),
            _edge("cond", "vm", "no"),
            _edge("cond", "b", "yes"),
        ],
    }
    res = validate_flow_graph(graph)
    assert not res.ok


def test_validator_rejects_cycle():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("a", "collect"),
            _node("b", "api"),
            _node("end", "end"),
        ],
        "edges": [
            _edge("g", "a"),
            _edge("a", "b"),
            _edge("b", "a"),  # cycle
        ],
    }
    res = validate_flow_graph(graph)
    assert not res.ok
    assert any("cycle" in e for e in res.errors)


def test_validator_warns_unreachable():
    graph = {
        "nodes": [
            _node("g", "greeting"),
            _node("c", "collect"),
            _node("end", "end"),
            _node("orphan", "api"),
        ],
        "edges": [_edge("g", "c"), _edge("c", "end")],
    }
    res = validate_flow_graph(graph)
    assert res.ok, res.errors
    assert any("unreachable" in w for w in res.warnings)


# ---------- publish-endpoint integration ----------------------------------


@pytest.mark.asyncio
async def test_publish_blocks_invalid_flow_graph(client, auth_headers):
    # Build agent with a bad flow_graph then try to publish.
    bad_graph = {"nodes": [_node("c", "collect")], "edges": []}  # no greeting
    r = await client.post(
        "/v1/agents",
        json={"name": "BadFlow", "first_message": "hi", "flow_graph": bad_graph},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]
    version_id = r.json()["versions"][0]["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/publish",
        json={"version_id": version_id, "env": "production"},
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "errors" in detail
    assert any("greeting" in e for e in detail["errors"])


@pytest.mark.asyncio
async def test_publish_passes_valid_flow_graph(client, auth_headers):
    good = {
        "nodes": [
            _node("g", "greeting"),
            _node("c", "collect"),
            _node("end", "end"),
        ],
        "edges": [_edge("g", "c"), _edge("c", "end")],
    }
    r = await client.post(
        "/v1/agents",
        json={"name": "GoodFlow", "first_message": "hi", "flow_graph": good},
        headers=auth_headers,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]
    version_id = r.json()["versions"][0]["id"]

    r = await client.post(
        f"/v1/agents/{agent_id}/publish",
        json={"version_id": version_id, "env": "production"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
