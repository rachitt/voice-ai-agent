"""Catalog endpoints — model + voice option lists."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_models_requires_auth(client):
    r = await client.get("/v1/models")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_models(client, auth_headers):
    r = await client.get("/v1/models", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(m["id"] == "gemini/gemini-3.1-flash-lite" for m in items)
    assert all({"id", "label", "vendor", "tier"} <= set(m) for m in items)


@pytest.mark.asyncio
async def test_list_voices(client, auth_headers):
    r = await client.get("/v1/voices", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(v["vendor"] == "elevenlabs" for v in items)


@pytest.mark.asyncio
async def test_voices_uses_live_elevenlabs_when_keyed(client, auth_headers, monkeypatch):
    from app.routers import catalog

    catalog._reset_voice_cache_for_tests()
    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", "secret", raising=False)

    async def fake_fetch(api_key: str):  # noqa: ARG001
        return [
            {"id": "el_aria", "label": "Aria (live)", "vendor": "elevenlabs", "latency": "fast"}
        ]

    monkeypatch.setattr(catalog, "_fetch_elevenlabs_voices", fake_fetch)
    r = await client.get("/v1/voices", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(v["id"] == "el_aria" for v in items)


@pytest.mark.asyncio
async def test_voices_falls_back_when_live_fails(client, auth_headers, monkeypatch):
    from app.routers import catalog

    catalog._reset_voice_cache_for_tests()
    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", "secret", raising=False)

    async def fail_fetch(api_key: str):  # noqa: ARG001
        return None

    monkeypatch.setattr(catalog, "_fetch_elevenlabs_voices", fail_fetch)
    r = await client.get("/v1/voices", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["items"]
    # Static fallback present (Sarah is the free-tier default; Rachel was
    # dropped because it's a library voice and 402s on free accounts).
    assert any(v["id"] == "EXAVITQu4vr4xnSDxMaL" for v in items)


@pytest.mark.asyncio
async def test_synthesize_requires_auth(client):
    r = await client.post("/v1/voices/v_abc/synthesize", json={"text": "hello"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_synthesize_returns_pcm(client, auth_headers, monkeypatch):
    from app.routers import catalog

    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", "secret", raising=False)

    async def fake_synth(*, text, voice_id, model_id="eleven_flash_v2_5", sample_rate=16000):  # noqa: ARG001
        # 1 ms of silence — enough to assert binary path without hitting the
        # network. Caller doesn't care what's in the bytes, only the wire
        # format + content-type.
        return b"\x00\x00" * 16

    monkeypatch.setattr(catalog, "synth_pcm", fake_synth)
    r = await client.post(
        "/v1/voices/v_abc/synthesize",
        headers=auth_headers,
        json={"text": "say hello"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["x-audio-format"] == "pcm_s16le_16000_mono"
    assert r.content == b"\x00\x00" * 16


@pytest.mark.asyncio
async def test_synthesize_503_when_unconfigured(client, auth_headers, monkeypatch):
    from app.routers import catalog

    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", None, raising=False)
    r = await client.post(
        "/v1/voices/v_abc/synthesize",
        headers=auth_headers,
        json={"text": "hi there"},
    )
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_synthesize_rejects_oversized_text(client, auth_headers, monkeypatch):
    from app.routers import catalog

    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", "secret", raising=False)
    # Pydantic field validator should 422 before we ever hit ElevenLabs.
    r = await client.post(
        "/v1/voices/v_abc/synthesize",
        headers=auth_headers,
        json={"text": "x" * 600},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_synthesize_502_on_provider_error(client, auth_headers, monkeypatch):
    from app.pipeline.tts import TtsProviderError
    from app.routers import catalog

    monkeypatch.setattr(catalog.get_settings(), "elevenlabs_api_key", "secret", raising=False)

    async def fail_synth(*, text, voice_id, model_id="eleven_flash_v2_5", sample_rate=16000):  # noqa: ARG001
        raise TtsProviderError("quota_exceeded")

    monkeypatch.setattr(catalog, "synth_pcm", fail_synth)
    r = await client.post(
        "/v1/voices/v_abc/synthesize",
        headers=auth_headers,
        json={"text": "anything"},
    )
    assert r.status_code == 502
    assert "quota_exceeded" in r.text
