"""CRUD for /v1/tools."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_tool_lifecycle(client, auth_headers):
    create = await client.post(
        "/v1/tools",
        headers=auth_headers,
        json={
            "name": "lookup",
            "server_url": "https://example.com/api/lookup",
            "method": "POST",
            "params_schema": {"type": "object"},
        },
    )
    assert create.status_code == 201, create.text
    tool_id = create.json()["id"]

    listing = await client.get("/v1/tools", headers=auth_headers)
    assert listing.status_code == 200
    assert any(t["id"] == tool_id for t in listing.json())

    patch = await client.patch(
        f"/v1/tools/{tool_id}",
        headers=auth_headers,
        json={"name": "lookup_v2", "timeout_ms": 20000, "description": "renamed"},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["name"] == "lookup_v2"
    assert body["timeout_ms"] == 20000
    assert body["description"] == "renamed"
    # Untouched fields preserved
    assert body["server_url"] == "https://example.com/api/lookup"

    miss = await client.patch(
        "/v1/tools/tool_does_not_exist", headers=auth_headers, json={"name": "x"}
    )
    assert miss.status_code == 404

    delete = await client.delete(f"/v1/tools/{tool_id}", headers=auth_headers)
    assert delete.status_code == 204
