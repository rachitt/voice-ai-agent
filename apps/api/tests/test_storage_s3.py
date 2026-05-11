"""storage.s3.put_object_bytes — gate + path tests."""
from __future__ import annotations

import pytest

from app.storage import s3 as s3mod


@pytest.mark.asyncio
async def test_put_object_noop_when_disabled(monkeypatch):
    # Default config has enable_object_store=False
    calls: list[tuple] = []

    def _fake_put_sync(bucket, key, data, content_type):
        calls.append((bucket, key, data, content_type))

    monkeypatch.setattr(s3mod, "_put_sync", _fake_put_sync)
    key = await s3mod.put_object_bytes(
        bucket="b", key="k", data=b"x", content_type="text/plain"
    )
    assert key is None
    assert calls == []


@pytest.mark.asyncio
async def test_put_object_calls_sync_when_enabled(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_OBJECT_STORE", "true")

    calls: list[tuple] = []

    def _fake_put_sync(bucket, key, data, content_type):
        calls.append((bucket, key, data, content_type))

    monkeypatch.setattr(s3mod, "_put_sync", _fake_put_sync)
    key = await s3mod.put_object_bytes(
        bucket="b", key="k", data=b"x", content_type="text/plain"
    )
    assert key == "k"
    assert calls == [("b", "k", b"x", "text/plain")]
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_put_object_returns_none_on_error(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_OBJECT_STORE", "true")

    def _boom(*args, **kwargs):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(s3mod, "_put_sync", _boom)
    key = await s3mod.put_object_bytes(
        bucket="b", key="k", data=b"x", content_type="text/plain"
    )
    assert key is None
    cfg.get_settings.cache_clear()
