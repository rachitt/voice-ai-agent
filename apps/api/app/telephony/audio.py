"""Audio transcode helpers for Telnyx Media Streaming.

Telnyx ships and accepts μ-law (G.711u) 8 kHz mono on its Media Streaming
WebSocket. Our pipeline speaks linear PCM 16-bit LE 16 kHz mono. This module
bridges the two formats.

Uses `audioop-lts` on Python ≥3.13 (where stdlib `audioop` was removed) and
the stdlib module on 3.11/3.12. Both expose the same API.
"""
from __future__ import annotations

# `audioop-lts` (declared in pyproject for py>=3.13) installs under the
# `audioop` module name, so this import works on 3.11/3.12 (stdlib) and
# 3.13+ (audioop-lts shim) without further branching. We silence the
# stdlib deprecation warning since we have the LTS shim ready for 3.13.
import warnings

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"'audioop' is deprecated.*")
    import audioop  # type: ignore[import-not-found]  # noqa: E402


TELNYX_SAMPLE_RATE = 8000
PIPELINE_SAMPLE_RATE = 16000


def ulaw_to_pcm16_16k(ulaw: bytes) -> bytes:
    """Decode μ-law 8 kHz → linear16 16 kHz mono."""
    pcm16_8k = audioop.ulaw2lin(ulaw, 2)
    pcm16_16k, _ = audioop.ratecv(pcm16_8k, 2, 1, TELNYX_SAMPLE_RATE, PIPELINE_SAMPLE_RATE, None)
    return pcm16_16k


def pcm16_16k_to_ulaw(pcm16_16k: bytes) -> bytes:
    """Encode linear16 16 kHz → μ-law 8 kHz mono."""
    pcm16_8k, _ = audioop.ratecv(pcm16_16k, 2, 1, PIPELINE_SAMPLE_RATE, TELNYX_SAMPLE_RATE, None)
    return audioop.lin2ulaw(pcm16_8k, 2)
