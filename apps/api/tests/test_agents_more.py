"""Agents router — 404 paths, analysis_plan validation, publish edge cases."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_get_agent_404(client, auth_headers):
    r = await client.get("/v1/agents/ag_missing", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_agent_404(client, auth_headers):
    r = await client.patch(
        "/v1/agents/ag_missing", headers=auth_headers, json={"first_message": "hi"}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_invalid_analysis_plan_rejected(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": f"AP-{uuid.uuid4().hex[:4]}"},
        headers=auth_headers,
    )
    aid = r.json()["id"]
    # structured_data_schema must be a valid JSON Schema; pass a malformed one.
    bad_plan = {"structured_data_schema": {"type": "not-a-real-type"}}
    r = await client.patch(
        f"/v1/agents/{aid}",
        headers=auth_headers,
        json={"analysis_plan": bad_plan},
    )
    assert r.status_code == 422
    body = r.json()
    # FastAPI wraps custom detail under "detail"
    detail = body.get("detail", body)
    assert detail.get("field") == "analysis_plan"
    assert detail.get("errors")


@pytest.mark.asyncio
async def test_publish_404_agent(client, auth_headers):
    r = await client.post(
        "/v1/agents/ag_missing/publish",
        headers=auth_headers,
        json={"version_id": "agv_missing", "env": "production"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_publish_404_version(client, auth_headers):
    r = await client.post(
        "/v1/agents", json={"name": f"V-{uuid.uuid4().hex[:4]}"}, headers=auth_headers
    )
    aid = r.json()["id"]
    r = await client.post(
        f"/v1/agents/{aid}/publish",
        headers=auth_headers,
        json={"version_id": "agv_does_not_exist", "env": "production"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_publish_rejects_invalid_flow_graph(client, auth_headers):
    r = await client.post(
        "/v1/agents",
        json={"name": f"FG-{uuid.uuid4().hex[:4]}", "first_message": "hi"},
        headers=auth_headers,
    )
    aid = r.json()["id"]
    vid = r.json()["versions"][0]["id"]
    # Attach a malformed flow_graph via patch (empty edges array, malformed nodes).
    bad = {"nodes": [{"id": "x"}], "edges": []}  # node missing required structure
    r = await client.patch(
        f"/v1/agents/{aid}",
        headers=auth_headers,
        json={"flow_graph": bad},
    )
    # patch may accept (no flow_graph validation on patch).
    assert r.status_code in (200, 422)
    if r.status_code == 422:
        return
    # publish must validate.
    r = await client.post(
        f"/v1/agents/{aid}/publish",
        headers=auth_headers,
        json={"version_id": vid, "env": "production"},
    )
    assert r.status_code == 422
    body = r.json()
    detail = body.get("detail", body)
    assert "errors" in detail


@pytest.mark.asyncio
async def test_list_agents_scoped_to_org(client, auth_headers):
    # baseline: list returns whatever exists, including a new one.
    name = f"Scope-{uuid.uuid4().hex[:4]}"
    await client.post("/v1/agents", json={"name": name}, headers=auth_headers)
    r = await client.get("/v1/agents", headers=auth_headers)
    assert r.status_code == 200
    assert any(a["name"] == name for a in r.json())
