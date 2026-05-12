"""Sweep remaining cold spots in analysis/runner, analysis/scheduler,
and webhooks/dispatcher."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.analysis import runner as analysis_runner
from app.analysis import scheduler as analysis_scheduler
from app.core.config import get_settings
from app.db import models
from app.webhooks import dispatcher as wh


# ---------- runner ---------------------------------------------------------


def test_format_transcript_empty_returns_placeholder():
    assert analysis_runner._format_transcript(None) == "(empty)"
    assert analysis_runner._format_transcript([]) == "(empty)"


def test_format_transcript_renders_lines():
    out = analysis_runner._format_transcript(
        [{"who": "user", "text": "hi"}, {"who": "agent", "text": "yo"}]
    )
    assert "[user] hi" in out and "[agent] yo" in out


@pytest.mark.asyncio
async def test_analyze_call_uses_legacy_plan_on_call_analysis(db_session, monkeypatch):
    """When AgentVersion has no plan, fall back to call.analysis['plan']."""
    canned = {"summary": "ok", "success": '{"success":true}'}

    async def _complete(*, model_id, messages, temperature=0.0, **kw):
        sys_msg = next((m.content for m in messages if m.role == "system"), "")
        text = canned["success"] if "strict JSON" in sys_msg else canned["summary"]
        return {"choices": [{"message": {"content": text}}]}

    monkeypatch.setattr(analysis_runner, "complete", _complete)

    org = models.Org(name="L", slug="legacy-plan")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(agent_id=agent.id, version=1)  # no analysis_plan
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        agent_version_id=ver.id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "x"}],
        analysis={"plan": {"summary_prompt": "shorter please"}},
    )
    db_session.add(call)
    await db_session.commit()

    out = await analysis_runner.analyze_call(db_session, call_id=call.id)
    assert out["summary"] == "ok"


@pytest.mark.asyncio
async def test_analyze_structured_bad_json_returns_error_envelope(db_session, monkeypatch):
    async def _complete(*, model_id, messages, temperature=0.0, **kw):
        sys_msg = next((m.content for m in messages if m.role == "system"), "")
        if "ONLY valid JSON" in sys_msg:
            return {"choices": [{"message": {"content": "not even close to json"}}]}
        if "strict JSON" in sys_msg:
            return {"choices": [{"message": {"content": '{"success":true}'}}]}
        return {"choices": [{"message": {"content": "sum"}}]}

    monkeypatch.setattr(analysis_runner, "complete", _complete)

    org = models.Org(name="BJ", slug="bad-json")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(
        agent_id=agent.id,
        version=1,
        analysis_plan={"structured_data_schema": {"type": "object"}},
    )
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        agent_version_id=ver.id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "x"}],
    )
    db_session.add(call)
    await db_session.commit()
    out = await analysis_runner.analyze_call(db_session, call_id=call.id)
    assert out["structured_data"]["_error"] == "bad_json"
    assert out["structured_data"]["_raw"].startswith("not even")


@pytest.mark.asyncio
async def test_analyze_success_bad_json_returns_could_not_parse(db_session, monkeypatch):
    async def _complete(*, model_id, messages, temperature=0.0, **kw):
        sys_msg = next((m.content for m in messages if m.role == "system"), "")
        if "strict JSON" in sys_msg:
            return {"choices": [{"message": {"content": "??? not json"}}]}
        return {"choices": [{"message": {"content": "summary"}}]}

    monkeypatch.setattr(analysis_runner, "complete", _complete)

    org = models.Org(name="SX", slug="success-bad")
    db_session.add(org)
    await db_session.flush()
    agent = models.Agent(org_id=org.id, name="A")
    db_session.add(agent)
    await db_session.flush()
    ver = models.AgentVersion(agent_id=agent.id, version=1)
    db_session.add(ver)
    await db_session.flush()
    call = models.Call(
        org_id=org.id,
        agent_id=agent.id,
        agent_version_id=ver.id,
        direction=models.CallDirection.web,
        status=models.CallStatus.completed,
        transcript=[{"role": "user", "text": "x"}],
    )
    db_session.add(call)
    await db_session.commit()
    out = await analysis_runner.analyze_call(db_session, call_id=call.id)
    assert out["success_evaluation"] == {"success": False, "reason": "could_not_parse"}


# ---------- scheduler ------------------------------------------------------


@pytest.mark.asyncio
async def test_scheduler_swallows_exception(monkeypatch, db_session):
    """_run_safely logs and returns None when analyze_call raises."""
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

    async def _boom(*args, **kw):
        raise RuntimeError("analysis blew up")

    monkeypatch.setattr(analysis_scheduler, "analyze_call", _boom)
    task = analysis_scheduler.schedule_post_call("call_doesnt_matter")
    assert task is not None
    result = await task
    assert result is None


# ---------- webhooks dispatcher --------------------------------------------


@pytest.mark.asyncio
async def test_run_once_returns_zero_when_no_pending(db_session, monkeypatch):
    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wh, "SessionLocal", _SL())
    assert await wh.run_once() == 0


@pytest.mark.asyncio
async def test_run_once_marks_dead_after_max_attempts(db_session, monkeypatch):
    """Three previous failures + another failure → status='dead'."""

    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wh, "SessionLocal", _SL())

    org = models.Org(name="WD", slug="wh-dead")
    db_session.add(org)
    await db_session.flush()
    row = models.WebhookOutbox(
        id="whx_dead",
        org_id=org.id,
        url="https://hooks.example/never",
        event="x",
        payload={},
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        status="pending",
        attempts=wh.MAX_ATTEMPTS - 1,  # one more failure tips it over
    )
    db_session.add(row)
    await db_session.commit()

    # Force every delivery to fail.
    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(_handler)

    real_client_cls = wh.httpx.AsyncClient

    class _ClientFactory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_client_cls(*a, **kw)

    monkeypatch.setattr(wh.httpx, "AsyncClient", _ClientFactory())
    processed = await wh.run_once()
    assert processed == 1
    db_session.expire_all()
    refreshed = await db_session.get(models.WebhookOutbox, "whx_dead")
    assert refreshed.status == "dead"
    assert refreshed.attempts == wh.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_run_once_backs_off_on_transient_failure(db_session, monkeypatch):
    """Below MAX_ATTEMPTS, failure schedules a future retry."""

    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(wh, "SessionLocal", _SL())

    org = models.Org(name="WB", slug="wh-back")
    db_session.add(org)
    await db_session.flush()
    row = models.WebhookOutbox(
        id="whx_retry",
        org_id=org.id,
        url="https://hooks.example/retry",
        event="x",
        payload={},
        next_attempt_at=datetime.now(UTC) - timedelta(seconds=1),
        status="pending",
        attempts=0,
    )
    db_session.add(row)
    await db_session.commit()

    def _handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(_handler)
    real_client_cls = wh.httpx.AsyncClient

    class _ClientFactory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_client_cls(*a, **kw)

    monkeypatch.setattr(wh.httpx, "AsyncClient", _ClientFactory())
    await wh.run_once()
    db_session.expire_all()
    refreshed = await db_session.get(models.WebhookOutbox, "whx_retry")
    assert refreshed.status == "pending"
    assert refreshed.attempts == 1
    assert refreshed.next_attempt_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_deliver_one_swallows_network_exception():
    """deliver_one logs and returns False on httpx exception."""

    class _Boom:
        async def post(self, *a, **kw):
            raise httpx.ConnectError("dns")

    class _Row:
        id = "whx_x"
        url = "https://nope.example"
        event = "x"
        payload = {}

    ok = await wh.deliver_one(_Boom(), _Row())
    assert ok is False


@pytest.mark.asyncio
async def test_run_forever_tick_then_cancel(monkeypatch):
    """run_forever loops once, then cancellation breaks out cleanly."""
    ticks = {"n": 0}

    async def fake_run_once():
        ticks["n"] += 1
        return 0

    async def fake_sleep(_):
        # After first tick, cancel ourselves so the loop exits.
        raise asyncio.CancelledError()

    monkeypatch.setattr(wh, "run_once", fake_run_once)
    monkeypatch.setattr(wh.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await wh.run_forever(poll_s=0.0)
    assert ticks["n"] == 1


@pytest.mark.asyncio
async def test_run_forever_logs_tick_error(monkeypatch):
    """A run_once exception is caught + logged; loop continues to sleep."""
    state = {"n": 0}

    async def fake_run_once():
        state["n"] += 1
        raise RuntimeError("boom")

    async def fake_sleep(_):
        if state["n"] >= 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr(wh, "run_once", fake_run_once)
    monkeypatch.setattr(wh.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await wh.run_forever(poll_s=0.0)
    assert state["n"] == 1
