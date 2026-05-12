"""knowledge_bases router: CRUD endpoints not covered by upload/query tests."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_create_then_list_kb(client, auth_headers):
    name = f"KB-{uuid.uuid4().hex[:4]}"
    r = await client.post(
        "/v1/knowledge-bases",
        headers=auth_headers,
        json={"name": name, "embedding_model": "text-embedding-3-small"},
    )
    assert r.status_code == 201, r.text
    kb_id = r.json()["id"]
    assert r.json()["name"] == name

    rl = await client.get("/v1/knowledge-bases", headers=auth_headers)
    assert rl.status_code == 200
    assert any(x["id"] == kb_id for x in rl.json())


@pytest.mark.asyncio
async def test_add_source_body_then_list_sources(client, auth_headers):
    r = await client.post(
        "/v1/knowledge-bases",
        headers=auth_headers,
        json={"name": f"KB-{uuid.uuid4().hex[:4]}", "embedding_model": "text-embedding-3-small"},
    )
    kb_id = r.json()["id"]

    s = await client.post(
        f"/v1/knowledge-bases/{kb_id}/sources",
        headers=auth_headers,
        json={"name": "doc.txt", "kind": "txt"},
    )
    assert s.status_code == 201, s.text
    src_id = s.json()["id"]

    lst = await client.get(f"/v1/knowledge-bases/{kb_id}/sources", headers=auth_headers)
    assert lst.status_code == 200
    assert any(x["id"] == src_id for x in lst.json())


@pytest.mark.asyncio
async def test_add_source_404_for_unknown_kb(client, auth_headers):
    r = await client.post(
        "/v1/knowledge-bases/kb_missing/sources",
        headers=auth_headers,
        json={"name": "x.txt", "kind": "txt"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_sources_404_for_unknown_kb(client, auth_headers):
    r = await client.get("/v1/knowledge-bases/kb_missing/sources", headers=auth_headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_query_404_for_unknown_kb(client, auth_headers):
    r = await client.post(
        "/v1/knowledge-bases/kb_missing/query", headers=auth_headers, json={"query": "x"}
    )
    assert r.status_code == 404
