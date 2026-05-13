// Browser web-call client.
//   - Opens WS to API
//   - Captures mic via AudioWorklet, sends 16 kHz Int16 PCM as binary
//   - Receives agent PCM binary, resamples to AudioContext rate, schedules playback
//   - Surfaces server JSON events to a callback
//
// Sample rate: 16 kHz on the wire (matches Deepgram + ElevenLabs PCM_16000).

const SAMPLE_RATE = 16000

export type WebCallEvent =
  | { type: 'open' }
  | { type: 'close'; code: number; reason: string }
  | { type: 'error'; error: string }
  | { type: 'server'; data: Record<string, unknown> }

export interface WebCallOpts {
  wsUrl: string // absolute or path. Resolved against window.location for path.
  onEvent: (e: WebCallEvent) => void
  textOnly?: boolean
}

export class WebCallClient {
  private ws: WebSocket | null = null
  private ac: AudioContext | null = null
  private worklet: AudioWorkletNode | null = null
  private micStream: MediaStream | null = null
  private playHead = 0
  private closed = false
  private opts: WebCallOpts

  constructor(opts: WebCallOpts) {
    this.opts = opts
  }

  async connect(opts: { apiBase: string }): Promise<void> {
    const wsUrl = this.resolveUrl(this.opts.wsUrl, opts.apiBase)
    const url = this.opts.textOnly
      ? `${wsUrl}${wsUrl.includes('?') ? '&' : '?'}text_only=true`
      : wsUrl
    this.ws = new WebSocket(url)
    this.ws.binaryType = 'arraybuffer'

    this.ws.onopen = () => this.opts.onEvent({ type: 'open' })
    this.ws.onclose = (e) =>
      this.opts.onEvent({ type: 'close', code: e.code, reason: e.reason })
    this.ws.onerror = () => this.opts.onEvent({ type: 'error', error: 'websocket' })
    this.ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        try {
          const data = JSON.parse(e.data)
          this.opts.onEvent({ type: 'server', data })
        } catch {
          // ignore
        }
        return
      }
      this.playPcm(e.data as ArrayBuffer)
    }

    if (!this.opts.textOnly) {
      await this.startMic()
    } else {
      // still need an AudioContext for playback
      this.ac = new AudioContext()
    }
  }

  private resolveUrl(p: string, apiBase: string): string {
    if (p.startsWith('ws://') || p.startsWith('wss://')) return p
    // WS authentication is already covered by the HMAC `ws_token` query
    // param the server minted, so the WebSocket itself doesn't need the
    // session cookie. That lets it bypass the vite dev proxy (whose WS
    // upgrade path EPIPEs under Vite 8) and connect direct to the API.
    //
    // In prod the build constant resolves to the same origin as the page,
    // so this still works without a separate WS host.
    const origin =
      typeof __VITE_API_ORIGIN__ === 'string' && __VITE_API_ORIGIN__
        ? __VITE_API_ORIGIN__
        : apiBase || `${window.location.protocol}//${window.location.host}`
    const base = origin.replace(/^http/, 'ws')
    return `${base}${p}`
  }

  private async startMic(): Promise<void> {
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    this.ac = new AudioContext()
    await this.ac.audioWorklet.addModule('/pcm-capture-worklet.js')
    const src = this.ac.createMediaStreamSource(this.micStream)
    this.worklet = new AudioWorkletNode(this.ac, 'pcm-capture', {
      processorOptions: { targetRate: SAMPLE_RATE, frameSamples: 640 },
    })
    this.worklet.port.onmessage = (e) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
      this.ws.send(e.data as ArrayBuffer)
    }
    src.connect(this.worklet)
    // Do NOT connect worklet to destination — we don't want mic to play back
  }

  /** Send a user text turn (bypasses STT). */
  sendUserText(text: string, isFinal = true): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return
    this.ws.send(JSON.stringify({ type: 'user_text', text, is_final: isFinal }))
  }

  /** Mute the mic without tearing down the WS. Disabled tracks emit silence
   *  but keep the AudioWorklet alive, so unmuting resumes instantly without
   *  a new permission prompt. */
  setMicMuted(muted: boolean): void {
    if (!this.micStream) return
    for (const track of this.micStream.getAudioTracks()) track.enabled = !muted
  }

  /** Schedule one PCM chunk (Int16 LE @ 16 kHz mono) for playback. */
  private playPcm(buf: ArrayBuffer): void {
    if (!this.ac) return
    const i16 = new Int16Array(buf)
    if (i16.length === 0) return

    const acRate = this.ac.sampleRate
    const outLen = Math.floor((i16.length * acRate) / SAMPLE_RATE)
    const audioBuf = this.ac.createBuffer(1, outLen, acRate)
    const out = audioBuf.getChannelData(0)

    // Linear interpolation upsample 16 kHz → ac.sampleRate
    const ratio = SAMPLE_RATE / acRate
    for (let i = 0; i < outLen; i++) {
      const srcF = i * ratio
      const i0 = Math.floor(srcF)
      const i1 = Math.min(i0 + 1, i16.length - 1)
      const frac = srcF - i0
      const s = (i16[i0] * (1 - frac) + i16[i1] * frac) / 0x8000
      out[i] = s
    }

    const src = this.ac.createBufferSource()
    src.buffer = audioBuf
    src.connect(this.ac.destination)
    const now = this.ac.currentTime
    const startAt = Math.max(now, this.playHead)
    src.start(startAt)
    this.playHead = startAt + audioBuf.duration
  }

  hangup(): void {
    if (this.closed) return
    this.closed = true
    try {
      this.ws?.send(JSON.stringify({ type: 'hangup' }))
    } catch {
      // ignore
    }
    try {
      this.worklet?.disconnect()
    } catch {
      // ignore
    }
    this.micStream?.getTracks().forEach((t) => t.stop())
    setTimeout(() => {
      try {
        this.ws?.close()
      } catch {
        // ignore
      }
      try {
        this.ac?.close()
      } catch {
        // ignore
      }
    }, 50)
  }
}
