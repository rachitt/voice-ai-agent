"""kb_ingest async worker task. Tests the function in isolation (no Redis)."""
from __future__ import annotations

import pytest

from app.db import models
from app.workers import kb_ingest as kb_worker


@pytest.mark.asyncio
async def test_ingest_kb_source_marks_error_when_source_missing(monkeypatch):
    res = await kb_worker.ingest_kb_source({}, "kbs_does_not_exist")
    assert res["ok"] is False
    assert res["error"] == "source_not_found"


@pytest.mark.asyncio
async def test_ingest_kb_source_errors_without_s3_key(db_session, monkeypatch):
    org = models.Org(name="O", slug="kbw1")
    db_session.add(org)
    await db_session.flush()
    kb = models.KnowledgeBase(org_id=org.id, name="KB")
    db_session.add(kb)
    await db_session.flush()
    src = models.KbSource(kb_id=kb.id, name="x.txt", kind="txt", status="queued")
    db_session.add(src)
    await db_session.commit()

    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(kb_worker, "SessionLocal", _SL())

    res = await kb_worker.ingest_kb_source({}, src.id)
    assert res["ok"] is False
    assert res["error"] == "missing_s3_key"


@pytest.mark.asyncio
async def test_ingest_kb_source_happy_path(db_session, monkeypatch):
    org = models.Org(name="O2", slug="kbw2")
    db_session.add(org)
    await db_session.flush()
    kb = models.KnowledgeBase(org_id=org.id, name="KB", embedding_model="text-embedding-3-small")
    db_session.add(kb)
    await db_session.flush()
    src = models.KbSource(
        kb_id=kb.id, name="policy.txt", kind="txt", status="queued",
        s3_key=f"kb/{kb.id}/x/policy.txt",
    )
    db_session.add(src)
    await db_session.commit()

    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(kb_worker, "SessionLocal", _SL())

    async def fake_get(*, bucket, key):
        return b"Refund policy. Refunds in 3-5 days. " * 20

    monkeypatch.setattr(kb_worker, "get_object_bytes", fake_get)

    async def fake_embed(*, model_id, texts):
        return [[0.0] * 1536 for _ in texts]

    from app.kb import store as kb_store
    monkeypatch.setattr(kb_store, "embed", fake_embed)

    res = await kb_worker.ingest_kb_source({}, src.id)
    assert res["ok"] is True, res
    assert res["chunks"] > 0
    await db_session.refresh(src)
    assert src.status == "ready"


@pytest.mark.asyncio
async def test_ingest_kb_source_idempotent_on_ready(db_session, monkeypatch):
    org = models.Org(name="O3", slug="kbw3")
    db_session.add(org)
    await db_session.flush()
    kb = models.KnowledgeBase(org_id=org.id, name="KB")
    db_session.add(kb)
    await db_session.flush()
    src = models.KbSource(kb_id=kb.id, name="r.txt", kind="txt", status="ready", s3_key="x")
    db_session.add(src)
    await db_session.commit()

    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(kb_worker, "SessionLocal", _SL())

    res = await kb_worker.ingest_kb_source({}, src.id)
    assert res["ok"] is True
    assert res["already_ready"] is True


@pytest.mark.asyncio
async def test_enqueue_kb_ingest_noop_when_disabled(monkeypatch):
    # Default config: enable_async_kb_ingest=False
    job_id = await kb_worker.enqueue_kb_ingest("kbs_x")
    assert job_id is None
