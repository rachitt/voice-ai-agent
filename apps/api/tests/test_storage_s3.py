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
    key = await s3mod.put_object_bytes(bucket="b", key="k", data=b"x", content_type="text/plain")
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
    key = await s3mod.put_object_bytes(bucket="b", key="k", data=b"x", content_type="text/plain")
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
    key = await s3mod.put_object_bytes(bucket="b", key="k", data=b"x", content_type="text/plain")
    assert key is None
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_get_object_bytes_round_trip(monkeypatch):
    monkeypatch.setattr(s3mod, "_get_sync", lambda b, k: b"payload-bytes")
    out = await s3mod.get_object_bytes(bucket="b", key="k")
    assert out == b"payload-bytes"


@pytest.mark.asyncio
async def test_presign_get_url_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(s3mod, "_presign_get_sync", lambda *a, **kw: "should-not-be-called")
    url = await s3mod.presign_get_url(bucket="b", key="k")
    assert url is None


@pytest.mark.asyncio
async def test_presign_get_url_returns_url_when_enabled(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_OBJECT_STORE", "true")

    captured: dict = {}

    def _fake(bucket, key, expires_in, content_type):
        captured.update(bucket=bucket, key=key, expires_in=expires_in, content_type=content_type)
        return f"https://s3/{bucket}/{key}?sig=xyz"

    monkeypatch.setattr(s3mod, "_presign_get_sync", _fake)
    url = await s3mod.presign_get_url(
        bucket="b", key="rec/wav", expires_in=120, content_type="audio/wav"
    )
    assert url == "https://s3/b/rec/wav?sig=xyz"
    assert captured == {"bucket": "b", "key": "rec/wav", "expires_in": 120, "content_type": "audio/wav"}
    cfg.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_presign_get_url_returns_none_on_error(monkeypatch):
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ENABLE_OBJECT_STORE", "true")

    def _boom(*a, **kw):
        raise RuntimeError("sign down")

    monkeypatch.setattr(s3mod, "_presign_get_sync", _boom)
    url = await s3mod.presign_get_url(bucket="b", key="k")
    assert url is None
    cfg.get_settings.cache_clear()


def test_presign_get_sync_builds_params(monkeypatch):
    """_presign_get_sync forwards content_type into ResponseContentType."""
    captured: dict = {}

    class _FakeClient:
        def generate_presigned_url(self, op, *, Params, ExpiresIn):
            captured.update(op=op, params=Params, expires_in=ExpiresIn)
            return "url"

    monkeypatch.setattr(s3mod, "get_s3_client", lambda: _FakeClient())
    s3mod._presign_get_sync("buk", "obj", 60, "audio/wav")
    assert captured["op"] == "get_object"
    assert captured["params"] == {"Bucket": "buk", "Key": "obj", "ResponseContentType": "audio/wav"}
    assert captured["expires_in"] == 60


def test_presign_get_sync_omits_content_type(monkeypatch):
    captured: dict = {}

    class _FakeClient:
        def generate_presigned_url(self, op, *, Params, ExpiresIn):
            captured.update(params=Params)
            return "url"

    monkeypatch.setattr(s3mod, "get_s3_client", lambda: _FakeClient())
    s3mod._presign_get_sync("buk", "obj", 60, None)
    assert captured["params"] == {"Bucket": "buk", "Key": "obj"}


def test_put_sync_ensures_bucket_and_puts(monkeypatch):
    """_put_sync calls head_bucket; on miss creates bucket; then put_object."""
    calls: list[str] = []

    class _FakeClient:
        def head_bucket(self, Bucket):
            calls.append(f"head:{Bucket}")
            raise RuntimeError("404 NoSuchBucket")

        def create_bucket(self, Bucket):
            calls.append(f"create:{Bucket}")

        def put_object(self, *, Bucket, Key, Body, ContentType):
            calls.append(f"put:{Bucket}/{Key}:{ContentType}:{len(Body)}")

    monkeypatch.setattr(s3mod, "get_s3_client", lambda: _FakeClient())
    s3mod._put_sync("buk", "obj", b"hello", "text/plain")
    assert calls == ["head:buk", "create:buk", "put:buk/obj:text/plain:5"]


def test_put_sync_skips_create_when_bucket_exists(monkeypatch):
    calls: list[str] = []

    class _FakeClient:
        def head_bucket(self, Bucket):
            calls.append(f"head:{Bucket}")

        def create_bucket(self, Bucket):  # pragma: no cover - should not be called
            calls.append(f"create:{Bucket}")

        def put_object(self, **kw):
            calls.append(f"put:{kw['Bucket']}/{kw['Key']}")

    monkeypatch.setattr(s3mod, "get_s3_client", lambda: _FakeClient())
    s3mod._put_sync("buk", "obj", b"x", "text/plain")
    assert calls == ["head:buk", "put:buk/obj"]


def test_ensure_bucket_swallows_create_errors(monkeypatch, caplog):
    """If create_bucket raises (e.g. race), we log and continue."""

    class _FakeClient:
        def head_bucket(self, Bucket):
            raise RuntimeError("not found")

        def create_bucket(self, Bucket):
            raise RuntimeError("conflict")

    s3mod._ensure_bucket_sync(_FakeClient(), "buk")
    # No raise = pass.


def test_get_s3_client_constructs_boto(monkeypatch):
    """get_s3_client wires settings into boto3.client; cached after first call."""
    s3mod.get_s3_client.cache_clear()

    captured: dict = {}

    def _fake_boto_client(service, **kwargs):
        captured.update(service=service, **kwargs)
        return object()

    monkeypatch.setattr(s3mod.boto3, "client", _fake_boto_client)
    c1 = s3mod.get_s3_client()
    c2 = s3mod.get_s3_client()
    assert c1 is c2  # lru_cache
    assert captured["service"] == "s3"
    assert "region_name" in captured
    s3mod.get_s3_client.cache_clear()


def test_get_sync_reads_body(monkeypatch):
    class _Body:
        def read(self):
            return b"abc"

    class _FakeClient:
        def get_object(self, *, Bucket, Key):
            assert (Bucket, Key) == ("b", "k")
            return {"Body": _Body()}

    monkeypatch.setattr(s3mod, "get_s3_client", lambda: _FakeClient())
    assert s3mod._get_sync("b", "k") == b"abc"
