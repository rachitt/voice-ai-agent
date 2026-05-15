"""CRUD coverage for `/v1/phone-numbers` list + patch endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_phone_numbers_scoped_to_org(client, auth_headers):
    """List should return only this org's phone numbers, ordered by e164."""
    # Seed two numbers — list should yield both in e164 asc order.
    for e in ["+15557770002", "+15557770001"]:
        r = await client.post(
            "/v1/phone-numbers",
            json={"e164": e, "provider": "telnyx"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text

    r = await client.get("/v1/phone-numbers", headers=auth_headers)
    assert r.status_code == 200, r.text
    e164s = [row["e164"] for row in r.json()]
    assert e164s == ["+15557770001", "+15557770002"]


@pytest.mark.asyncio
async def test_patch_phone_number_updates_fields(client, auth_headers):
    """PATCH applies supplied fields and persists."""
    r = await client.post(
        "/v1/phone-numbers",
        json={"e164": "+15557770003", "provider": "telnyx"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    pn_id = r.json()["id"]

    # Seed an agent we can bind to.
    r = await client.post(
        "/v1/agents",
        json={"name": "PN Bind", "first_message": "hi", "system_prompt": "be brief"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    r = await client.patch(
        f"/v1/phone-numbers/{pn_id}",
        json={"agent_id": agent_id, "status": "active"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == agent_id
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_patch_phone_number_not_found(client, auth_headers):
    """Unknown id returns 404."""
    r = await client.patch(
        "/v1/phone-numbers/pn_does_not_exist",
        json={"status": "released"},
        headers=auth_headers,
    )
    assert r.status_code == 404, r.text
