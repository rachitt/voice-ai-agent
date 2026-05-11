"""Audio transcode helpers for Telnyx Media Streaming.

Telnyx ships and accepts μ-law (G.711u) 8 kHz mono on its Media Streaming
WebSocket. Our pipeline speaks linear PCM 16-bit LE 16 kHz mono. This module
bridges the two formats.

`audioop` is part of the stdlib in CPython 3.11 (deprecated in 3.13). The
runtime is pinned to 3.11 via pyproject; a fallback ships in case `audioop`
is removed in a future runtime.
"""
from __future__ import annotations

try:  # stdlib in 3.11
    import audioop  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback (3.13+)
    audioop = None  # type: ignore[assignment]


TELNYX_SAMPLE_RATE = 8000
PIPELINE_SAMPLE_RATE = 16000


def ulaw_to_pcm16_16k(ulaw: bytes) -> bytes:
    """Decode μ-law 8 kHz → linear16 16 kHz mono."""
    if audioop is None:
        raise RuntimeError("audioop unavailable — install audioop-lts on 3.13+")
    pcm16_8k = audioop.ulaw2lin(ulaw, 2)
    pcm16_16k, _ = audioop.ratecv(pcm16_8k, 2, 1, TELNYX_SAMPLE_RATE, PIPELINE_SAMPLE_RATE, None)
    return pcm16_16k


def pcm16_16k_to_ulaw(pcm16_16k: bytes) -> bytes:
    """Encode linear16 16 kHz → μ-law 8 kHz mono."""
    if audioop is None:
        raise RuntimeError("audioop unavailable — install audioop-lts on 3.13+")
    pcm16_8k, _ = audioop.ratecv(pcm16_16k, 2, 1, PIPELINE_SAMPLE_RATE, TELNYX_SAMPLE_RATE, None)
    return audioop.lin2ulaw(pcm16_8k, 2)
