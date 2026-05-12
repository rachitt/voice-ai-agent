"""catalog._fetch_elevenlabs_voices — exercise the HTTP layer directly."""

from __future__ import annotations

import httpx
import pytest

from app.routers import catalog


@pytest.fixture(autouse=True)
def _clear_cache():
    catalog._reset_voice_cache_for_tests()


@pytest.mark.asyncio
async def test_fetch_returns_normalised_voice_rows(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("xi-api-key") == "key-1"
        return httpx.Response(
            200,
            json={
                "voices": [
                    {"voice_id": "v1", "name": "Aria", "category": "fast"},
                    {"voice_id": "v2", "name": "Brando"},  # no category → default
                    {"name": "no-id-skipped"},  # missing voice_id → skipped
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    real_cls = catalog.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(catalog.httpx, "AsyncClient", _Factory())
    out = await catalog._fetch_elevenlabs_voices("key-1")
    assert out is not None
    assert [v["id"] for v in out] == ["v1", "v2"]
    assert out[0]["latency"] == "fast"
    assert out[1]["latency"] == "balanced"
    assert all(v["vendor"] == "elevenlabs" for v in out)


@pytest.mark.asyncio
async def test_fetch_returns_none_on_non_200(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate"})

    transport = httpx.MockTransport(handler)
    real_cls = catalog.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(catalog.httpx, "AsyncClient", _Factory())
    assert await catalog._fetch_elevenlabs_voices("k") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_empty_voice_list(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"voices": []})

    transport = httpx.MockTransport(handler)
    real_cls = catalog.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(catalog.httpx, "AsyncClient", _Factory())
    assert await catalog._fetch_elevenlabs_voices("k") is None


@pytest.mark.asyncio
async def test_fetch_returns_none_on_exception(monkeypatch):
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns fail")

    transport = httpx.MockTransport(handler)
    real_cls = catalog.httpx.AsyncClient

    class _Factory:
        def __call__(self, *a, **kw):
            kw["transport"] = transport
            return real_cls(*a, **kw)

    monkeypatch.setattr(catalog.httpx, "AsyncClient", _Factory())
    assert await catalog._fetch_elevenlabs_voices("k") is None


@pytest.mark.asyncio
async def test_voices_payload_serves_from_cache(monkeypatch):
    """Once we cache live voices, subsequent calls skip the HTTP path."""
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("VOICE_ELEVENLABS_API_KEY", "k")

    calls = {"n": 0}

    async def fake_fetch(_key: str):
        calls["n"] += 1
        return [{"id": "v_cached", "label": "C", "vendor": "elevenlabs", "latency": "fast"}]

    monkeypatch.setattr(catalog, "_fetch_elevenlabs_voices", fake_fetch)
    out1 = await catalog._voices_payload()
    out2 = await catalog._voices_payload()
    assert out1 == out2
    assert calls["n"] == 1
    cfg.get_settings.cache_clear()
