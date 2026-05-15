"""μ-law ↔ linear16 transcode roundtrip."""

from __future__ import annotations

import math

import pytest

audioop = pytest.importorskip("audioop")  # noqa: F401 — needed for 3.13 skip

from app.telephony.audio import pcm16_16k_to_ulaw, ulaw_to_pcm16_16k  # noqa: E402


def _sine_pcm16_16k(freq: int = 440, ms: int = 50) -> bytes:
    n = int(16000 * ms / 1000)
    out = bytearray()
    for i in range(n):
        s = int(math.sin(2 * math.pi * freq * i / 16000) * 0x3000)
        out += s.to_bytes(2, "little", signed=True)
    return bytes(out)


def test_pcm_to_ulaw_then_back_preserves_length_class():
    pcm = _sine_pcm16_16k(440, 60)
    ulaw = pcm16_16k_to_ulaw(pcm)
    assert len(ulaw) == len(pcm) // 4  # 16k → 8k halves, 16-bit → 8-bit halves again
    pcm2 = ulaw_to_pcm16_16k(ulaw)
    # Round-trip restores sample-rate; length should match within 1 sample
    assert abs(len(pcm2) - len(pcm)) <= 4
