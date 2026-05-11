"""Post-call analysis runner + scheduler (gated on enable_post_call_analysis)."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.analysis import runner as analysis_runner
from app.analysis import scheduler as analysis_scheduler
from app.core.config import get_settings
from app.db import models


@pytest.fixture
def fake_complete(monkeypatch):
    """Stub `complete()` to return canned responses without an LLM call."""
    canned = {"summary": "Two-line summary.", "structured": '{"intent":"refund"}', "success": '{"success":true,"reason":"resolved"}'}
    state = {"calls": 0}

    async def _complete(*, model_id, messages, temperature=0.0, **kw):
        state["calls"] += 1
        sys_msg = next((m.content for m in messages if m.role == "system"), "")
        if "ONLY valid JSON" in sys_msg:
            text = canned["structured"]
        elif "strict JSON" in sys_msg:
            text = canned["success"]
        else:
            text = canned["summary"]
        return {"choices": [{"message": {"content": text}}]}

    monkeypatch.setattr(analysis_runner, "complete", _complete)
    return state


@pytest.mark.asyncio
async def test_analyze_call_writes_summary_and_success(db_session, fake_complete):
    org = models.Org(name="A", slug="anaorg")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="X")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(agent_id=agent.id, version=1)
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id, agent_id=agent.id, agent_version_id=ver.id,
        direction=models.CallDirection.web, status=models.CallStatus.completed,
        transcript=[
            {"role": "user", "text": "I want a refund"},
            {"role": "assistant", "text": "Sure, processed."},
        ],
    )
    db_session.add(call)
    await db_session.commit()

    out = await analysis_runner.analyze_call(db_session, call_id=call.id)
    assert out["summary"] == "Two-line summary."
    assert out["success_evaluation"]["success"] is True
    # Re-fetch
    fresh = await db_session.get(models.Call, call.id)
    assert fresh.analysis["summary"] == "Two-line summary."


@pytest.mark.asyncio
async def test_analyze_call_uses_agent_version_analysis_plan(db_session, fake_complete):
    org = models.Org(name="B", slug="anaorgb")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="Y")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id, version=1,
        analysis_plan={
            "structured_data_schema": {"type": "object", "properties": {"intent": {"type": "string"}}},
        },
    )
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id, agent_id=agent.id, agent_version_id=ver.id,
        direction=models.CallDirection.web, status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "refund please"}],
    )
    db_session.add(call)
    await db_session.commit()

    out = await analysis_runner.analyze_call(db_session, call_id=call.id)
    assert "structured_data" in out
    assert out["structured_data"]["intent"] == "refund"


@pytest.mark.asyncio
async def test_analyze_call_missing_returns_lookup_error(db_session):
    with pytest.raises(LookupError):
        await analysis_runner.analyze_call(db_session, call_id="call_nope")


def test_schedule_post_call_noop_when_disabled():
    s = get_settings()
    s.enable_post_call_analysis = False
    assert analysis_scheduler.schedule_post_call("call_x") is None


@pytest.mark.asyncio
async def test_schedule_post_call_runs_when_enabled(db_session, monkeypatch, fake_complete):
    s = get_settings()
    monkeypatch.setattr(s, "enable_post_call_analysis", True, raising=False)

    # Replace SessionLocal so scheduler uses our test session.
    class _SL:
        def __call__(self):
            return self
        async def __aenter__(self):
            return db_session
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(analysis_scheduler, "SessionLocal", _SL())

    org = models.Org(name="C", slug="anaorgc")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="Z")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(agent_id=agent.id, version=1)
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id, agent_id=agent.id, agent_version_id=ver.id,
        direction=models.CallDirection.web, status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "hello"}],
    )
    db_session.add(call)
    await db_session.commit()
    call_id = call.id

    task = analysis_scheduler.schedule_post_call(call_id)
    assert task is not None
    result = await task
    assert result is not None
    assert "summary" in result


@pytest.mark.asyncio
async def test_scheduler_emits_outbox_webhook_when_server_url_set(
    db_session, monkeypatch, fake_complete
):
    s = get_settings()
    monkeypatch.setattr(s, "enable_post_call_analysis", True, raising=False)

    class _SL:
        def __call__(self):
            return self
        async def __aenter__(self):
            return db_session
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(analysis_scheduler, "SessionLocal", _SL())

    org = models.Org(name="D", slug="anaorgd")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="W")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id, version=1, server_url="https://hooks.example/analysis"
    )
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id, agent_id=agent.id, agent_version_id=ver.id,
        direction=models.CallDirection.web, status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "ok"}],
    )
    db_session.add(call)
    await db_session.commit()
    call_id = call.id

    task = analysis_scheduler.schedule_post_call(call_id)
    await task

    rows = (
        await db_session.execute(
            select(models.WebhookOutbox).where(models.WebhookOutbox.org_id == org.id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].event == "analysis.completed"
    assert rows[0].url == "https://hooks.example/analysis"
    assert rows[0].payload["call_id"] == call_id
