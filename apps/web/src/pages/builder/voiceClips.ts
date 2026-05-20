// Per-agent voice clips for the Test Call panel.
//
// A clip is Int16 PCM @ 16 kHz mono — the wire format both the
// pcm-capture-worklet (live mic) and the server-side synth endpoint
// (`POST /v1/voices/:voice_id/synthesize`) speak. Clips are minted by
// the synth endpoint and stored client-side as base64 in localStorage,
// then replayed back over the WS frame-by-frame at the worklet's 40 ms
// cadence so STT + barge-in treat them identically to live speech.
//
// Storage is base64 in localStorage. Raw int16@16k = 32 KB/s of audio,
// so a typical 3 s clip is ~100 KB raw / ~135 KB base64. localStorage
// gives us ~5 MB per origin → realistic ceiling of a few dozen clips
// per agent before we'd need to migrate to IndexedDB.

export const SAMPLE_RATE = 16000
export const FRAME_SAMPLES = 640 // 40 ms at 16 kHz, matches the worklet
export const FRAME_BYTES = FRAME_SAMPLES * 2 // Int16 = 2 bytes/sample
export const FRAME_MS = (FRAME_SAMPLES * 1000) / SAMPLE_RATE

export type VoiceClip = {
  id: string
  name: string
  durationMs: number
  createdAt: number
  /** Base64-encoded Int16 PCM, 16 kHz mono. */
  dataB64: string
}

const KEY = (agentId: string) => `voice2.voice_clips.${agentId}`

export function loadClips(agentId: string): VoiceClip[] {
  try {
    const raw = localStorage.getItem(KEY(agentId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (c): c is VoiceClip =>
        c &&
        typeof c.id === 'string' &&
        typeof c.name === 'string' &&
        typeof c.durationMs === 'number' &&
        typeof c.dataB64 === 'string',
    )
  } catch {
    return []
  }
}

export function saveClips(agentId: string, clips: VoiceClip[]): void {
  try {
    localStorage.setItem(KEY(agentId), JSON.stringify(clips))
  } catch {
    // Quota likely. Bubble nothing — caller's already shown the clip in
    // state and the worst case is it doesn't survive reload.
  }
}

export function nextClipId(): string {
  return `vc_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`
}

// btoa balks on raw binary strings past ~64 KB on some browsers; chunk so
// we don't blow up on near-max clips.
export function bytesToBase64(bytes: Uint8Array): string {
  const CHUNK = 0x8000
  let out = ''
  for (let i = 0; i < bytes.length; i += CHUNK) {
    out += String.fromCharCode(...bytes.subarray(i, i + CHUNK))
  }
  return btoa(out)
}

export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

