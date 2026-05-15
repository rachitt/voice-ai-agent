"""arq worker for webhook outbox: delivery, retries, dead-lettering, idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db import models
from app.webhooks import dispatcher
from app.workers import webhook_outbox as wh_worker


class _FakeResp:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _FakeClient:
    """Minimal httpx.AsyncClient stand-in for tests."""

    def __init__(self, status: int = 200, raise_exc: Exception | None = None) -> None:
        self.status = status
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, content=None, headers=None, timeout=None):
        self.calls.append({"url": url, "content": content, "headers": headers})
        if self.raise_exc:
            raise self.raise_exc
        return _FakeResp(self.status)


@pytest.fixture
def patch_session(db_session, monkeypatch):
    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(wh_worker, "SessionLocal", _SL())
    monkeypatch.setattr(dispatcher, "SessionLocal", _SL())
    return db_session


@pytest.fixture
async def org(db_session):
    o = models.Org(name="WO", slug="wh-org")
    db_session.add(o)
    await db_session.commit()
    return o


@pytest.mark.asyncio
async def test_deliver_webhook_marks_delivered_on_2xx(patch_session, org, monkeypatch):
    row = await dispatcher.enqueue(
        patch_session,
        org_id=org.id,
        url="https://example.com/hook",
        event="call.completed",
        payload={"x": 1},
    )

    fake = _FakeClient(status=204)
    monkeypatch.setattr(wh_worker.httpx, "AsyncClient", lambda *a, **kw: fake)

    row_id = row.id
    res = await wh_worker.deliver_webhook({}, row_id)
    assert res == {"ok": True, "id": row_id, "status": "delivered"}

    patch_session.expire_all()
    fresh = await patch_session.get(models.WebhookOutbox, row_id)
    assert fresh.status == "delivered"
    assert fresh.delivered_at is not None
    assert fresh.attempts == 1
    assert fake.calls[0]["headers"]["x-voice-event"] == "call.completed"
    assert "x-voice-signature" in fake.calls[0]["headers"]


@pytest.mark.asyncio
async def test_deliver_webhook_retries_with_backoff(patch_session, org, monkeypatch):
    row = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://example.com/h", event="e", payload={}
    )
    fake = _FakeClient(status=500)
    monkeypatch.setattr(wh_worker.httpx, "AsyncClient", lambda *a, **kw: fake)

    row_id = row.id
    before = datetime.now(UTC)
    res = await wh_worker.deliver_webhook({}, row_id)
    assert res["ok"] is False
    patch_session.expire_all()
    fresh = await patch_session.get(models.WebhookOutbox, row_id)
    assert fresh.status == "pending"
    assert fresh.attempts == 1
    # backoff pushed it into the future
    assert fresh.next_attempt_at > before


@pytest.mark.asyncio
async def test_deliver_webhook_dead_after_max_attempts(patch_session, org, monkeypatch):
    row = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://e.com", event="e", payload={}
    )
    # Pretend we're already at MAX_ATTEMPTS - 1
    row.attempts = dispatcher.MAX_ATTEMPTS - 1
    await patch_session.commit()
    row_id = row.id

    fake = _FakeClient(raise_exc=RuntimeError("boom"))
    monkeypatch.setattr(wh_worker.httpx, "AsyncClient", lambda *a, **kw: fake)

    res = await wh_worker.deliver_webhook({}, row_id)
    assert res["ok"] is False
    patch_session.expire_all()
    fresh = await patch_session.get(models.WebhookOutbox, row_id)
    assert fresh.status == "dead"


@pytest.mark.asyncio
async def test_deliver_webhook_idempotent_for_already_delivered(patch_session, org, monkeypatch):
    row = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://e.com", event="e", payload={}
    )
    row.status = "delivered"
    row.delivered_at = datetime.now(UTC)
    await patch_session.commit()
    row_id = row.id

    sentinel = _FakeClient(status=500)
    monkeypatch.setattr(wh_worker.httpx, "AsyncClient", lambda *a, **kw: sentinel)

    res = await wh_worker.deliver_webhook({}, row_id)
    assert res["already_done"] is True
    assert sentinel.calls == []


@pytest.mark.asyncio
async def test_deliver_webhook_not_found(patch_session):
    res = await wh_worker.deliver_webhook({}, "whx_not_real")
    assert res == {"ok": False, "error": "outbox_not_found", "id": "whx_not_real"}


@pytest.mark.asyncio
async def test_tick_processes_due_rows_only(patch_session, org, monkeypatch):
    # one due, one scheduled in the future
    due = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://due.example", event="e", payload={}
    )
    future = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://future.example", event="e", payload={}
    )
    future.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    await patch_session.commit()
    due_id, future_id = due.id, future.id

    fake = _FakeClient(status=200)
    monkeypatch.setattr(dispatcher.httpx, "AsyncClient", lambda *a, **kw: fake)

    res = await wh_worker.tick_webhook_outbox({})
    assert res == {"ok": True, "processed": 1}
    assert fake.calls[0]["url"] == "https://due.example"

    patch_session.expire_all()
    due_fresh = await patch_session.get(models.WebhookOutbox, due_id)
    future_fresh = await patch_session.get(models.WebhookOutbox, future_id)
    assert due_fresh.status == "delivered"
    assert future_fresh.status == "pending"


@pytest.mark.asyncio
async def test_enqueue_noop_when_disabled():
    # default config: enable_webhook_worker=False
    res = await wh_worker.enqueue_webhook_delivery("whx_x")
    assert res is None


@pytest.mark.asyncio
async def test_pending_count_only_counts_due(patch_session, org):
    a = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://a", event="e", payload={}
    )
    b = await dispatcher.enqueue(
        patch_session, org_id=org.id, url="https://b", event="e", payload={}
    )
    b.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
    await patch_session.commit()
    assert await wh_worker.pending_count() == 1
    assert a.id  # silence unused-var
