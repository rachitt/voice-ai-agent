"""GET /v1/calls — list + filter + keyset pagination."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import models


async def _seed_calls(db_session, org, agent_id: str, n: int) -> list[models.Call]:
    rows: list[models.Call] = []
    base = datetime.now(UTC) - timedelta(hours=n)
    for i in range(n):
        c = models.Call(
            org_id=org.id,
            agent_id=agent_id,
            direction=models.CallDirection.web,
            status=models.CallStatus.completed,
            from_number=f"+1555000{i:04d}",
            to_number="+15550000999",
            recording_s3_key=f"rec/{i}.wav" if i % 2 == 0 else None,
        )
        # Manually back-date so ordering is deterministic.
        c.created_at = base + timedelta(minutes=i)
        db_session.add(c)
        rows.append(c)
    await db_session.commit()
    return rows


@pytest.mark.asyncio
async def test_list_returns_newest_first(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "A", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    await _seed_calls(db_session, org, agent_id, 5)

    r = await client.get("/v1/calls", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    assert len(items) == 5
    # Newest first
    timestamps = [it["created_at"] for it in items]
    assert timestamps == sorted(timestamps, reverse=True)
    # has_recording flag set
    assert any(it["has_recording"] for it in items)
    assert any(not it["has_recording"] for it in items)


@pytest.mark.asyncio
async def test_list_filters_by_agent(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "A1", "first_message": "Hi"}, headers=auth_headers
    )
    a1 = r.json()["id"]
    r = await client.post(
        "/v1/agents", json={"name": "A2", "first_message": "Hi"}, headers=auth_headers
    )
    a2 = r.json()["id"]
    await _seed_calls(db_session, org, a1, 3)
    await _seed_calls(db_session, org, a2, 2)

    r = await client.get(f"/v1/calls?agent_id={a1}", headers=auth_headers)
    items = r.json()["items"]
    assert len(items) == 3
    assert all(it["agent_id"] == a1 for it in items)


@pytest.mark.asyncio
async def test_list_filters_has_recording(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "A3", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    await _seed_calls(db_session, org, agent_id, 5)

    r = await client.get("/v1/calls?has_recording=true", headers=auth_headers)
    items = r.json()["items"]
    assert items
    assert all(it["has_recording"] for it in items)

    r = await client.get("/v1/calls?has_recording=false", headers=auth_headers)
    items = r.json()["items"]
    assert items
    assert all(not it["has_recording"] for it in items)


@pytest.mark.asyncio
async def test_list_paginates_via_cursor(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "A4", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    await _seed_calls(db_session, org, agent_id, 7)

    r = await client.get("/v1/calls?limit=3", headers=auth_headers)
    body = r.json()
    assert len(body["items"]) == 3
    cursor = body["next_cursor"]
    assert cursor is not None

    seen_ids = {it["id"] for it in body["items"]}
    r = await client.get(f"/v1/calls?limit=3&cursor={cursor}", headers=auth_headers)
    body = r.json()
    assert len(body["items"]) == 3
    for it in body["items"]:
        assert it["id"] not in seen_ids
        seen_ids.add(it["id"])

    # Last page
    r = await client.get(f"/v1/calls?limit=3&cursor={body['next_cursor']}", headers=auth_headers)
    body = r.json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_isolates_orgs(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "Mine", "first_message": "Hi"}, headers=auth_headers
    )
    mine = r.json()["id"]
    await _seed_calls(db_session, org, mine, 2)

    other_org = models.Org(name="Other", slug="other-list")
    db_session.add(other_org)
    await db_session.flush()
    other_call = models.Call(
        org_id=other_org.id,
        agent_id=mine,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
    )
    db_session.add(other_call)
    await db_session.commit()

    r = await client.get("/v1/calls", headers=auth_headers)
    items = r.json()["items"]
    assert len(items) == 2
    other_id = other_call.id
    assert all(it["id"] != other_id for it in items)


@pytest.mark.asyncio
async def test_get_call_returns_detail_with_transcript(client, db_session, auth_headers):
    org = (await db_session.execute(select(models.Org))).scalars().first()
    r = await client.post(
        "/v1/agents", json={"name": "D", "first_message": "Hi"}, headers=auth_headers
    )
    agent_id = r.json()["id"]
    call = models.Call(
        org_id=org.id,
        agent_id=agent_id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "Hello"}],
        provider_call_id="cc_xyz",
    )
    db_session.add(call)
    await db_session.commit()

    r = await client.get(f"/v1/calls/{call.id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == [{"role": "user", "text": "Hello"}]
    assert body["provider_call_id"] == "cc_xyz"


@pytest.mark.asyncio
async def test_list_rejects_bad_cursor(client, auth_headers):
    r = await client.get("/v1/calls?cursor=not-valid", headers=auth_headers)
    assert r.status_code == 400
