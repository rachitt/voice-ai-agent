"""squads router: create / list / get with agent validation."""

from __future__ import annotations

import uuid

import pytest


async def _new_agent(client, headers, name: str) -> str:
    r = await client.post("/v1/agents", headers=headers, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_squad_with_edges_then_get(client, auth_headers):
    a1 = await _new_agent(client, auth_headers, f"r-{uuid.uuid4().hex[:4]}")
    a2 = await _new_agent(client, auth_headers, f"c-{uuid.uuid4().hex[:4]}")
    body = {
        "name": "Demo Squad",
        "root_agent_id": a1,
        "edges": [
            {"from_agent_id": a1, "to_agent_id": a2, "context_policy": "last", "context_n": 5}
        ],
    }
    r = await client.post("/v1/squads", headers=auth_headers, json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["name"] == "Demo Squad"
    assert out["root_agent_id"] == a1
    assert len(out["edges"]) == 1
    sid = out["id"]

    # GET single
    g = await client.get(f"/v1/squads/{sid}", headers=auth_headers)
    assert g.status_code == 200
    assert g.json()["id"] == sid

    # LIST
    lst = await client.get("/v1/squads", headers=auth_headers)
    assert lst.status_code == 200
    assert any(s["id"] == sid for s in lst.json())


@pytest.mark.asyncio
async def test_create_squad_rejects_unknown_agent(client, auth_headers):
    a1 = await _new_agent(client, auth_headers, f"u-{uuid.uuid4().hex[:4]}")
    body = {
        "name": "Bad",
        "root_agent_id": a1,
        "edges": [{"from_agent_id": a1, "to_agent_id": "ag_does_not_exist"}],
    }
    r = await client.post("/v1/squads", headers=auth_headers, json=body)
    assert r.status_code == 400
    assert "not found" in r.json()["detail"]


@pytest.mark.asyncio
async def test_get_squad_404(client, auth_headers):
    r = await client.get("/v1/squads/sq_missing", headers=auth_headers)
    assert r.status_code == 404
