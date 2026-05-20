"""Model + voice catalog.

Models stay static (one row per `model_id` we route to). Voices are pulled
live from ElevenLabs when an API key is configured, falling back to the
static list when it isn't. The live list is cached in-process for an hour
to keep `AgentSettingsPanel` snappy and stay under ElevenLabs' rate cap.
"""

from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.core.auth import AuthedPrincipal, require_principal
from app.core.config import get_settings
from app.core.logging import log
from app.pipeline.tts import TtsProviderError, synth_pcm

router = APIRouter(prefix="/v1", tags=["catalog"])

_VOICE_CACHE_TTL = 3600  # seconds
_voice_cache: dict[str, object] | None = None
_voice_cache_at: float = 0.0


async def _fetch_elevenlabs_voices(api_key: str) -> list[dict] | None:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key},
            )
        if r.status_code != 200:
            log.warning("catalog.el.bad_status", status=r.status_code)
            return None
        data = r.json()
        voices = data.get("voices", []) if isinstance(data, dict) else []
        out: list[dict] = []
        for v in voices:
            vid = v.get("voice_id")
            name = v.get("name") or vid
            if not vid:
                continue
            out.append(
                {
                    "id": vid,
                    "label": name,
                    "vendor": "elevenlabs",
                    "latency": v.get("category", "balanced"),
                }
            )
        return out or None
    except Exception as exc:
        log.warning("catalog.el.err", err=str(exc))
        return None


async def _voices_payload() -> list[dict]:
    """Return the voice list, preferring live ElevenLabs over the static fallback."""
    global _voice_cache, _voice_cache_at
    settings = get_settings()
    if _voice_cache is not None and (time.time() - _voice_cache_at) < _VOICE_CACHE_TTL:
        return _voice_cache  # type: ignore[return-value]
    if settings.elevenlabs_api_key:
        live = await _fetch_elevenlabs_voices(settings.elevenlabs_api_key)
        if live:
            _voice_cache = live  # type: ignore[assignment]
            _voice_cache_at = time.time()
            return live
    # Fallback: don't poison the cache, so we retry on the next request.
    return list(_VOICES)


def _reset_voice_cache_for_tests() -> None:  # used by pytest fixtures
    global _voice_cache, _voice_cache_at
    _voice_cache = None
    _voice_cache_at = 0.0


_MODELS = [
    {
        "id": "gemini/gemini-2.5-flash",
        "label": "Gemini 2.5 Flash",
        "vendor": "google",
        "tier": "fast",
    },
    {
        "id": "gemini/gemini-3.1-flash-lite",
        "label": "Gemini 3.1 Flash Lite",
        "vendor": "google",
        "tier": "fast",
    },
    {
        "id": "gemini/gemini-3.1-pro",
        "label": "Gemini 3.1 Pro",
        "vendor": "google",
        "tier": "smart",
    },
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "vendor": "openai", "tier": "fast"},
    {"id": "gpt-4o", "label": "GPT-4o", "vendor": "openai", "tier": "smart"},
    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "vendor": "anthropic", "tier": "fast"},
    {
        "id": "claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "vendor": "anthropic",
        "tier": "smart",
    },
]

# Static fallback used when no live ElevenLabs key is configured.
# IDs are public ElevenLabs voice IDs (NOT TTS model ids).
_VOICES = [
    # Premade voices — accessible on free tier. Library voices (e.g. Rachel
    # 21m00Tcm4TlvDq8ikWAM) require a paid plan and 402 on free accounts.
    {"id": "EXAVITQu4vr4xnSDxMaL", "label": "Sarah", "vendor": "elevenlabs", "latency": "fast"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam", "vendor": "elevenlabs", "latency": "fast"},
    {"id": "hpp4J3VqNfWAUOO0d1Us", "label": "Bella", "vendor": "elevenlabs", "latency": "fast"},
    {"id": "JBFqnCBsd6RMkjVDRZzb", "label": "George", "vendor": "elevenlabs", "latency": "fast"},
]


@router.get("/models")
async def list_models(_: AuthedPrincipal = Depends(require_principal)) -> dict[str, list[dict]]:
    return {"items": _MODELS}


@router.get("/voices")
async def list_voices(_: AuthedPrincipal = Depends(require_principal)) -> dict[str, list[dict]]:
    return {"items": await _voices_payload()}


# Hard cap mirrors how short canned utterances are in practice ("Yes",
# "my email is foo@bar.com", "Tomorrow at 3pm") — well under the limit.
# Keeps a runaway request from burning a lot of ElevenLabs credits.
_SYNTH_MAX_CHARS = 500


class SynthesizeBody(BaseModel):
    text: str = Field(min_length=1, max_length=_SYNTH_MAX_CHARS)


@router.post("/voices/{voice_id}/synthesize")
async def synthesize_voice(
    voice_id: str,
    body: SynthesizeBody,
    _: AuthedPrincipal = Depends(require_principal),
) -> Response:
    """Synthesize `body.text` with `voice_id` → return PCM16 LE @ 16 kHz mono.

    Used by the Test Call panel to mint canned voice clips on demand. The
    bytes returned are the exact wire format the live mic worklet uses, so
    the browser can stream them back over the same WS as if a human spoke.
    Hits the shared TTS Redis cache, so repeated synthesis of the same
    (voice, text) pair is free."""
    if not get_settings().elevenlabs_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "elevenlabs not configured — set VOICE_ELEVENLABS_API_KEY",
        )
    try:
        pcm = await synth_pcm(text=body.text, voice_id=voice_id)
    except TtsProviderError as exc:
        # 502 — upstream provider rejected. Carries through quota/voice-id
        # messages so the UI can render a useful banner instead of 'failed'.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"tts: {exc}") from exc
    except Exception as exc:
        log.warning("synthesize.err", err=str(exc), voice_id=voice_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "synthesis failed") from exc

    if not pcm:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "tts: empty response")

    return Response(
        content=pcm,
        media_type="application/octet-stream",
        headers={
            # Mark with the wire format so a curl debug session is unambiguous.
            "x-audio-format": "pcm_s16le_16000_mono",
            "x-audio-byte-rate": "32000",  # 16000 Hz * 2 bytes/sample
        },
    )
