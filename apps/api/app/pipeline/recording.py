"""Per-call audio recorder.

Accumulates inbound (user) and outbound (agent) PCM 16-bit LE @ 16 kHz mono
into two parallel buffers. On `finalise()`, pads the shorter side with
silence and interleaves into a stereo WAV (left=user, right=agent) so the
two speakers stay independently audible in playback / annotation tools.

The recorder is mode-agnostic — both the browser WS bridge and the Telnyx
media bridge push the same linear16-16k samples into it.
"""
from __future__ import annotations

import io
import wave

PIPELINE_SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes per sample (16-bit)


class CallRecorder:
    """Lightweight per-call audio buffer. Not thread-safe — owned by the WS task."""

    def __init__(self, sample_rate: int = PIPELINE_SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._user = bytearray()
        self._agent = bytearray()
        self._closed = False

    def push_user(self, pcm16: bytes) -> None:
        if not self._closed and pcm16:
            self._user.extend(pcm16)

    def push_agent(self, pcm16: bytes) -> None:
        if not self._closed and pcm16:
            self._agent.extend(pcm16)

    def has_audio(self) -> bool:
        return bool(self._user) or bool(self._agent)

    def total_duration_ms(self) -> int:
        frames = max(len(self._user), len(self._agent)) // SAMPLE_WIDTH
        if frames == 0:
            return 0
        return int(frames * 1000 / self.sample_rate)

    def finalise(self) -> bytes:
        """Return stereo WAV bytes (left=user, right=agent). Resets internal state."""
        self._closed = True
        # Pad shorter side with silence so both channels run for the same duration.
        target_len = max(len(self._user), len(self._agent))
        if target_len == 0:
            return b""
        user = bytes(self._user) + b"\x00" * (target_len - len(self._user))
        agent = bytes(self._agent) + b"\x00" * (target_len - len(self._agent))

        frame_count = target_len // SAMPLE_WIDTH
        interleaved = bytearray(target_len * 2)
        for i in range(frame_count):
            base = i * SAMPLE_WIDTH
            out = i * SAMPLE_WIDTH * 2
            interleaved[out : out + SAMPLE_WIDTH] = user[base : base + SAMPLE_WIDTH]
            interleaved[out + SAMPLE_WIDTH : out + SAMPLE_WIDTH * 2] = agent[base : base + SAMPLE_WIDTH]

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(SAMPLE_WIDTH)
            wf.setframerate(self.sample_rate)
            wf.writeframes(bytes(interleaved))
        return buf.getvalue()


def recording_key(*, org_id: str, call_id: str) -> str:
    """S3 key for a call's recording. Scoped by org so a bucket compromise
    doesn't immediately let you enumerate across tenants."""
    return f"recordings/{org_id}/{call_id}.wav"
