"""kb_ingest worker — cold paths: kb-deleted, exception during ingest,
enqueue + WorkerSettings.redis_settings."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.db import models
from app.workers import kb_ingest as worker


@pytest.fixture
def patched_sessionlocal(db_session, monkeypatch):
    class _SL:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(worker, "SessionLocal", _SL())
    return db_session


@pytest.mark.asyncio
async def test_ingest_marks_error_when_kb_deleted(patched_sessionlocal, monkeypatch):
    """KbSource exists but its KnowledgeBase row has been deleted.

    Mock `db.get(KnowledgeBase, ...)` to return None instead of breaking the
    FK constraint at insert time."""
    db = patched_sessionlocal
    org = models.Org(name="O", slug="kb-orphan")
    db.add(org)
    await db.flush()
    kb = models.KnowledgeBase(id="kb_alive", org_id=org.id, name="K", embedding_model="m")
    db.add(kb)
    await db.flush()
    src = models.KbSource(
        id="kbs_orphan",
        kb_id=kb.id,
        name="x.txt",
        kind="txt",
        s3_key="kb/x.txt",
        status="queued",
    )
    db.add(src)
    await db.commit()

    real_get = db.get

    async def _stub_get(model, ident, *a, **kw):
        if model is models.KnowledgeBase:
            return None
        return await real_get(model, ident, *a, **kw)

    monkeypatch.setattr(db, "get", _stub_get)
    out = await worker.ingest_kb_source({}, "kbs_orphan")
    assert out == {"ok": False, "error": "kb_not_found", "source_id": "kbs_orphan"}
    monkeypatch.setattr(db, "get", real_get)
    db.expire_all()
    refreshed = await real_get(models.KbSource, "kbs_orphan")
    assert refreshed.status == "error"
    assert "kb deleted" in (refreshed.error or "")


@pytest.mark.asyncio
async def test_ingest_marks_error_when_extract_raises(
    patched_sessionlocal, monkeypatch
):
    db = patched_sessionlocal
    org = models.Org(name="O", slug="kb-err")
    db.add(org)
    await db.flush()
    kb = models.KnowledgeBase(id="kb_err", org_id=org.id, name="K", embedding_model="m")
    db.add(kb)
    await db.flush()
    src = models.KbSource(
        id="kbs_err",
        kb_id=kb.id,
        name="x.txt",
        kind="txt",
        s3_key="kb/x.txt",
        status="queued",
    )
    db.add(src)
    await db.commit()

    async def fake_get_bytes(*, bucket, key):
        return b"raw-bytes"

    def boom(*a, **kw):
        raise RuntimeError("extract blew up")

    monkeypatch.setattr(worker, "get_object_bytes", fake_get_bytes)
    monkeypatch.setattr(worker, "extract_text", boom)

    out = await worker.ingest_kb_source({}, "kbs_err")
    assert out["ok"] is False
    assert "extract blew up" in out["error"]
    db.expire_all()
    refreshed = await db.get(models.KbSource, "kbs_err")
    assert refreshed.status == "error"
    assert "extract blew up" in (refreshed.error or "")


@pytest.mark.asyncio
async def test_enqueue_kb_ingest_pushes_when_enabled(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_ASYNC_KB_INGEST", "true")

    # Fake the arq.connections module so we don't need a real Redis.
    pool_calls: dict[str, Any] = {}

    class _Job:
        job_id = "job_123"

    class _Pool:
        async def enqueue_job(self, name, *args, **kw):
            pool_calls["name"] = name
            pool_calls["args"] = args
            return _Job()

        async def aclose(self):
            pool_calls["closed"] = True

    async def fake_create_pool(_settings):
        return _Pool()

    fake_mod = types.SimpleNamespace(
        RedisSettings=types.SimpleNamespace(from_dsn=lambda url: ("rs", url)),
        create_pool=fake_create_pool,
    )
    monkeypatch.setitem(sys.modules, "arq.connections", fake_mod)

    out = await worker.enqueue_kb_ingest("kbs_xyz")
    assert out == "job_123"
    assert pool_calls["name"] == "ingest_kb_source"
    assert pool_calls["args"] == ("kbs_xyz",)
    assert pool_calls["closed"] is True
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_enqueue_returns_none_when_job_none(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_ASYNC_KB_INGEST", "true")

    class _Pool:
        async def enqueue_job(self, *a, **kw):
            return None

        async def aclose(self):
            pass

    async def fake_create_pool(_):
        return _Pool()

    fake_mod = types.SimpleNamespace(
        RedisSettings=types.SimpleNamespace(from_dsn=lambda url: ("rs", url)),
        create_pool=fake_create_pool,
    )
    monkeypatch.setitem(sys.modules, "arq.connections", fake_mod)
    out = await worker.enqueue_kb_ingest("kbs_x")
    assert out is None
    cfg.get_settings.cache_clear()


def test_worker_settings_redis_settings(monkeypatch):
    """Static method should call arq.connections.RedisSettings.from_dsn(url)."""
    captured: dict[str, Any] = {}

    fake_mod = types.SimpleNamespace(
        RedisSettings=types.SimpleNamespace(
            from_dsn=lambda url: captured.setdefault("url", url) or ("rs",)
        )
    )
    monkeypatch.setitem(sys.modules, "arq.connections", fake_mod)
    worker.WorkerSettings.redis_settings()
    assert captured["url"].startswith("redis://")
