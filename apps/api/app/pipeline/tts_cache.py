"""Redis-backed audio cache for ElevenLabs TTS output.

ElevenLabs charges per character synthesised. A surprising fraction of those
characters are stable strings that we resay on every call: the agent's
`first_message`, the per-flow-node `prompt`, canned tool-call interstitials,
and any voicemail/transfer scripts. Re-synthesising them is pure waste.

This module wraps `_speak` with an opportunistic lookup:

    key  = sha256(voice_id || tts_model || sample_rate || text)
    hit  → yield the cached PCM frames, charge nothing
    miss → synth as normal, write the concatenated PCM back under the key

PCM is stable across calls: same voice + same model + same text = byte-for-byte
identical waveform, so we don't risk drift. TTL is 30 days — long enough that
any agent's first_message survives ordinary editing churn, short enough that
revoked voices fall out of the cache before they become stale evidence.

Failures are silent: Redis down or full → fall through to a real synth, so
nobody loses a call to a cache hiccup.
"""

from __future__ import annotations

import hashlib
from typing import Final

import redis.asyncio as redis

from app.core.config import get_settings
from app.core.logging import log

_TTL_SECONDS: Final[int] = 60 * 60 * 24 * 30  # 30 days
_MIN_TEXT_LEN: Final[int] = 4  # skip "hi", "ok", single tokens — not worth a roundtrip
_MAX_VALUE_BYTES: Final[int] = 4 * 1024 * 1024  # 4 MB cap; ~2 min of PCM @ 16 kHz mono LE16

_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url)
    return _client


def _key(*, voice_id: str, tts_model_id: str, sample_rate: int, text: str) -> str:
    raw = f"{voice_id}|{tts_model_id}|{sample_rate}|{text}".encode()
    return f"tts:v1:{hashlib.sha256(raw).hexdigest()}"


async def get_pcm(*, voice_id: str, tts_model_id: str, sample_rate: int, text: str) -> bytes | None:
    """Look up previously-synthesised PCM. Returns None on miss or any error
    so callers can treat it as "synth path"."""
    norm = text.strip()
    if len(norm) < _MIN_TEXT_LEN:
        return None
    try:
        return await _redis().get(
            _key(
                voice_id=voice_id,
                tts_model_id=tts_model_id,
                sample_rate=sample_rate,
                text=norm,
            )
        )
    except Exception as exc:
        log.warning("tts_cache.get.err", err=str(exc))
        return None


async def put_pcm(
    *,
    voice_id: str,
    tts_model_id: str,
    sample_rate: int,
    text: str,
    pcm: bytes,
) -> None:
    norm = text.strip()
    if len(norm) < _MIN_TEXT_LEN or not pcm:
        return
    if len(pcm) > _MAX_VALUE_BYTES:
        return  # don't blow the cache on a runaway response
    try:
        await _redis().setex(
            _key(
                voice_id=voice_id,
                tts_model_id=tts_model_id,
                sample_rate=sample_rate,
                text=norm,
            ),
            _TTL_SECONDS,
            pcm,
        )
    except Exception as exc:
        log.warning("tts_cache.put.err", err=str(exc))
