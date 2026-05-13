"""GET /v1/console/summary — checklist + today + launches."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db import models


@pytest.mark.asyncio
async def test_summary_empty_org(client, auth_headers):
    r = await client.get("/v1/console/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {
        "checklist",
        "today",
        "recent_tool_calls",
        "launch_history",
        "score_breakdown",
        "compliance",
    }
    # First incomplete step marked as current
    statuses = [c["status"] for c in body["checklist"]]
    assert statuses[0] == "current"  # phone is first todo
    assert body["today"]["calls"] == 0


@pytest.mark.asyncio
async def test_summary_checklist_progresses(client, auth_headers, db_session):
    # Add agent, phone number, KB → checklist should progress
    me = await client.get("/v1/auth/me")  # ensure no crash for unrelated auth
    assert me.status_code == 401  # session vs bearer

    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    from sqlalchemy import select

    from app.core.security import hash_api_key

    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    assert org_row is not None
    _, org = org_row

    db_session.add(models.PhoneNumber(org_id=org.id, e164="+15551234567"))
    db_session.add(models.KnowledgeBase(org_id=org.id, name="KB1"))
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id,
        version=1,
        env="production",
        system_prompt="be helpful",
        tools=["end_call"],
    )
    db_session.add(ver)
    await db_session.flush()
    agent.published_version_id = ver.id
    await db_session.commit()

    r = await client.get("/v1/console/summary", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    statuses = {c["key"]: c["status"] for c in body["checklist"]}
    assert statuses["phone"] == "done"
    assert statuses["kb"] == "done"
    assert statuses["guardrails"] == "done"
    assert statuses["tools"] == "done"
    assert statuses["launch"] == "done"

    assert len(body["launch_history"]) == 1
    assert body["launch_history"][0]["env"] == "production"
    assert body["launch_history"][0]["version"] == "v1"


@pytest.mark.asyncio
async def test_summary_today_rollup(client, auth_headers, db_session):
    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    from sqlalchemy import select

    from app.core.security import hash_api_key

    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    _, org = org_row

    agent = models.Agent(org_id=org.id, name="X")
    db_session.add(agent)
    await db_session.flush()

    now = datetime.now(UTC)
    for status_, dur in [("completed", 12000), ("completed", 8000), ("failed", 2000)]:
        c = models.Call(
            org_id=org.id,
            agent_id=agent.id,
            direction="web",
            status=status_,
            duration_ms=dur,
        )
        c.created_at = now
        db_session.add(c)
    await db_session.commit()

    r = await client.get("/v1/console/summary", headers=auth_headers)
    body = r.json()
    today = body["today"]
    assert today["calls"] == 3
    assert today["completed"] == 2
    assert today["failed"] == 1
    assert today["avg_duration_ms"] == int((12000 + 8000 + 2000) / 3)


@pytest.mark.asyncio
async def test_summary_requires_auth(client):
    r = await client.get("/v1/console/summary")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_analytics_empty_org(client, auth_headers):
    r = await client.get("/v1/console/analytics?range=7d", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["range"] == "7d"
    assert body["total_calls"] == 0
    assert body["success_rate"] == 0.0
    assert body["avg_duration_ms"] == 0
    assert len(body["volume_by_day"]) == 7
    assert body["by_agent"] == []


@pytest.mark.asyncio
async def test_analytics_aggregates(client, auth_headers, db_session):
    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    from sqlalchemy import select

    from app.core.security import hash_api_key

    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    _, org = org_row

    agent = models.Agent(org_id=org.id, name="Support")
    db_session.add(agent)
    await db_session.flush()

    now = datetime.now(UTC)
    samples = [
        ("completed", 10000),
        ("completed", 20000),
        ("completed", 30000),
        ("failed", 5000),
    ]
    for status_, dur in samples:
        c = models.Call(
            org_id=org.id,
            agent_id=agent.id,
            direction="web",
            status=status_,
            duration_ms=dur,
        )
        c.created_at = now
        db_session.add(c)
    await db_session.commit()

    r = await client.get("/v1/console/analytics?range=7d", headers=auth_headers)
    body = r.json()
    assert body["total_calls"] == 4
    assert body["success_rate"] == 0.75
    assert body["avg_duration_ms"] == int((10000 + 20000 + 30000 + 5000) / 4)
    assert body["p95_duration_ms"] > 0
    assert len(body["by_agent"]) == 1
    assert body["by_agent"][0]["name"] == "Support"
    assert body["by_agent"][0]["count"] == 4
    assert body["by_agent"][0]["success_rate"] == 0.75


@pytest.mark.asyncio
async def test_analytics_uses_analysis_verdict_when_present(client, auth_headers, db_session):
    bearer = auth_headers["Authorization"].split(" ", 1)[1]
    from sqlalchemy import select

    from app.core.security import hash_api_key

    org_row = (
        await db_session.execute(
            select(models.ApiKey, models.Org)
            .join(models.Org, models.Org.id == models.ApiKey.org_id)
            .where(models.ApiKey.key_hash == hash_api_key(bearer))
        )
    ).first()
    _, org = org_row

    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()

    now = datetime.now(UTC)
    # Three calls: status=completed but analysis says failure; status=failed
    # but analysis says success; status=completed w/ no analysis.
    rows = [
        ("completed", {"success_evaluation": {"success": False}}),
        ("failed", {"success_evaluation": {"success": True}}),
        ("completed", None),
    ]
    for status_, analysis in rows:
        c = models.Call(
            org_id=org.id,
            agent_id=agent.id,
            direction="web",
            status=status_,
            duration_ms=1000,
            analysis=analysis,
        )
        c.created_at = now
        db_session.add(c)
    await db_session.commit()

    r = await client.get("/v1/console/analytics?range=7d", headers=auth_headers)
    body = r.json()
    # Successes: row 1 (analysis says false → 0) + row 2 (analysis says true → 1)
    # + row 3 (no analysis, status=completed → 1) = 2/3
    assert body["total_calls"] == 3
    assert body["success_rate"] == pytest.approx(2 / 3, rel=1e-6)


@pytest.mark.asyncio
async def test_analytics_bad_range_falls_back(client, auth_headers):
    r = await client.get("/v1/console/analytics?range=lol", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["range"] == "7d"
    assert len(body["volume_by_day"]) == 7
