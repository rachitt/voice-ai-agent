import { useEffect, useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  CircleDashed,
  Loader2,
  Mic,
  MicOff,
  PhoneOff,
  Play,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  Volume2,
  Wrench,
  X,
} from 'lucide-react'
import { api, getApiBase } from '@/lib/api'
import { WebCallClient, type WebCallEvent } from '@/lib/webcall'
import { cn } from '@/lib/cn'
import { useBuilder } from './store'
import { KIND_ICON, KIND_TINT } from './icons'
import {
  base64ToBytes,
  bytesToBase64,
  FRAME_BYTES,
  FRAME_MS,
  loadClips,
  nextClipId,
  SAMPLE_RATE,
  saveClips,
  type VoiceClip,
} from './voiceClips'

type TranscriptKind = 'text' | 'tool_call' | 'tool_result' | 'error'
type TranscriptLine = {
  role: 'user' | 'agent' | 'system'
  text: string
  at: number
  kind: TranscriptKind
}

function fmtTime(ts: number) {
  const d = new Date(ts)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/**
 * Test Call panel. Renders inside the right-side inspector as a tab — not a
 * modal, not a floater — so the user can flip back to the Node tab and keep
 * editing the flow without tearing down the call.
 *
 * Real voice call, not a chat. Browser mic streams 16-bit PCM up via
 * WebSocket; agent PCM replies stream back through `<AudioContext>`. The
 * text input is a fallback channel for when the mic is busted or for
 * deterministic QA. Tucked behind a disclosure so the surface reads as
 * "voice first".
 *
 * Voice state derives from event timing:
 *   - "Listening"   when WS is live, agent isn't streaming text
 *   - "Agent speaking" while agent_text deltas arrive before turn_end
 *   - "Connecting" / "Closed" / "Error" — terminal states
 */
export function TestCallPanel({
  agentId,
  agentVariableDefaults,
  onClose,
}: {
  agentId: string
  agentVariableDefaults?: Record<string, unknown>
  onClose: () => void
}) {
  const [status, setStatus] = useState<'connecting' | 'live' | 'closed' | 'error'>('connecting')
  const [err, setErr] = useState<string | null>(null)
  // Non-fatal provider errors that arrive mid-call. TTS quota exhaustion is
  // the common one: LLM still streams agent_text, but no audio comes back.
  // We surface this here so users don't think the agent went deaf.
  const [ttsError, setTtsError] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const [textOnly, setTextOnly] = useState(false)
  const [muted, setMuted] = useState(false)
  const [showText, setShowText] = useState(false)
  const [agentSpeaking, setAgentSpeaking] = useState(false)
  const [textInput, setTextInput] = useState('')
  const [overrides, setOverrides] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      Object.entries(agentVariableDefaults || {}).map(([k, v]) => [
        k,
        typeof v === 'string' ? v : JSON.stringify(v),
      ]),
    ),
  )
  const [lastUserText, setLastUserText] = useState<string | null>(null)
  const [clips, setClips] = useState<VoiceClip[]>(() => loadClips(agentId))
  const [newClipText, setNewClipText] = useState('')
  const [synthesizing, setSynthesizing] = useState(false)
  const [synthError, setSynthError] = useState<string | null>(null)
  const [playingClipId, setPlayingClipId] = useState<string | null>(null)
  // playbackTimerRef    — interval id paced at FRAME_MS while replaying
  // playbackCancelRef   — flag to short-circuit the next playback tick
  const playbackTimerRef = useRef<number | null>(null)
  const playbackCancelRef = useRef<boolean>(false)
  const clientRef = useRef<WebCallClient | null>(null)
  // Voice id used to synthesize new clips. Pulled from the agent meta on
  // demand so a voice swap mid-session takes effect for the next clip.
  const agentVoiceId = useBuilder((s) => s.agentMeta?.voiceId)
  const startedRef = useRef(false)
  const transcriptScrollRef = useRef<HTMLDivElement | null>(null)
  const setActiveFlowNodeId = useBuilder((s) => s.setActiveFlowNodeId)
  // Live node context — driven by `flow_node` events on the WS. The chip in
  // the header below uses these to show "Currently: <node title>" so the
  // user can debug the flow without tabbing back to the canvas.
  const activeFlowProgress = useBuilder((s) => s.activeFlowProgress)
  const activeNode = useBuilder((s) =>
    s.activeFlowNodeId ? (s.nodes.find((n) => n.id === s.activeFlowNodeId) ?? null) : null,
  )

  async function start(useTextOnly: boolean) {
    if (startedRef.current) return
    startedRef.current = true
    try {
      const created = await api.createWebCall(agentId, overrides)
      try {
        localStorage.setItem('voice2.watch_call_id', created.id)
      } catch {
        /* private mode */
      }
      const c = new WebCallClient({
        wsUrl: created.ws_url,
        textOnly: useTextOnly,
        onEvent: (e: WebCallEvent) => {
          if (e.type === 'open') setStatus('live')
          if (e.type === 'close') {
            setStatus('closed')
            setAgentSpeaking(false)
            setActiveFlowNodeId(null)
          }
          if (e.type === 'error') {
            setStatus('error')
            setErr(e.error)
            setAgentSpeaking(false)
            setActiveFlowNodeId(null)
          }
          if (e.type === 'server') {
            const d = e.data as {
              type?: string
              text?: string
              data?: {
                node_id?: string
                kind?: string
                progress?: { filled: string[]; missing: string[] }
              }
            }
            const t = d.type
            if (t === 'flow_node' && d.data?.node_id) {
              setActiveFlowNodeId(d.data.node_id, d.data.progress ?? null)
            } else if (t === 'tts_error') {
              const msg = (d.data as { err?: string } | undefined)?.err ?? 'tts unavailable'
              setTtsError(msg)
              setAgentSpeaking(false)
            } else if (t === 'user_text' && d.text) {
              append('user', d.text, 'text')
              setLastUserText(d.text)
              setAgentSpeaking(false)
            } else if (t === 'agent_text' && d.text) {
              append('agent', d.text, 'text')
              setAgentSpeaking(true)
            } else if (t === 'turn_end') {
              setAgentSpeaking(false)
            } else if (t === 'tool_call') {
              append('system', d.text ?? '', 'tool_call')
            } else if (t === 'tool_result') {
              append('system', d.text ?? '', 'tool_result')
            } else if (t === 'error') {
              append('system', JSON.stringify(d), 'error')
            } else if (t === 'warn') {
              // Server-side soft failure (e.g. STT init blew up because
              // VOICE_DEEPGRAM_API_KEY isn't set). Surface as an error
              // card so users don't think the agent has gone deaf.
              const w = d as { warn?: string; detail?: string }
              append('system', `warn: ${w.warn ?? '?'}${w.detail ? ` — ${w.detail}` : ''}`, 'error')
            } else if (t === 'stt') {
              // Interim + final Deepgram transcripts. Surfaces what STT
              // hears in near-real-time — invaluable when a voice clip
              // streams but the agent doesn't react (lets you tell
              // "Deepgram heard nothing" from "Deepgram heard but didn't
              // endpoint"). Only render finals to keep the transcript
              // readable; interims would spam.
              const s = d as { text?: string; is_final?: boolean; speech_final?: boolean }
              if (s.text && s.is_final) {
                const tag = s.speech_final ? 'stt·final' : 'stt'
                append('system', `${tag}: ${s.text}`, 'text')
              }
            }
          }
        },
      })
      clientRef.current = c
      await c.connect({ apiBase: getApiBase() })
    } catch (e) {
      setStatus('error')
      setErr(String(e))
    }
  }

  function append(
    role: 'user' | 'agent' | 'system',
    text: string,
    kind: TranscriptKind = 'text',
  ) {
    setTranscript((t) => [...t, { role, text, at: Date.now(), kind }])
  }

  function end() {
    clientRef.current?.hangup()
    clientRef.current = null
    setStatus('closed')
    setAgentSpeaking(false)
    setActiveFlowNodeId(null)
  }

  function toggleMute() {
    const next = !muted
    setMuted(next)
    clientRef.current?.setMicMuted?.(next)
  }

  function sendUtterance(t: string) {
    const text = t.trim()
    if (!text || !clientRef.current || status !== 'live') return
    clientRef.current.sendUserText(text)
    append('user', text, 'text')
    setLastUserText(text)
  }

  function sendText() {
    if (!textInput.trim()) return
    sendUtterance(textInput)
    setTextInput('')
  }

  function replayLastUser() {
    if (lastUserText) sendUtterance(lastUserText)
  }

  async function synthesizeClip() {
    const text = newClipText.trim()
    if (!text || synthesizing) return
    if (!agentVoiceId) {
      setSynthError('Agent has no voice configured.')
      return
    }
    setSynthError(null)
    setSynthesizing(true)
    try {
      const buf = await api.synthesizeClip(agentVoiceId, text)
      const bytes = new Uint8Array(buf)
      if (bytes.byteLength === 0) {
        setSynthError('TTS returned empty audio.')
        return
      }
      const durationMs = Math.round((bytes.byteLength / 2 / 16000) * 1000)
      const clip: VoiceClip = {
        id: nextClipId(),
        name: text.length > 40 ? `${text.slice(0, 40)}…` : text,
        durationMs,
        createdAt: Date.now(),
        dataB64: bytesToBase64(bytes),
      }
      const next = [...clips, clip]
      setClips(next)
      saveClips(agentId, next)
      setNewClipText('')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      // Surface the upstream provider message when we get a 502 carrying
      // ElevenLabs' explanation (quota_exceeded, voice_not_found, …).
      setSynthError(msg)
    } finally {
      setSynthesizing(false)
    }
  }

  function playClip(clip: VoiceClip) {
    const c = clientRef.current
    if (!c || status !== 'live') return
    if (playingClipId) stopPlayback()
    playbackCancelRef.current = false
    setPlayingClipId(clip.id)
    // Mute the live mic during playback so the agent doesn't get two audio
    // streams overlapping (real silence + the clip). Restored on finish.
    const wasMuted = muted
    c.setMicMuted?.(true)

    // Clip + silence tail. Deepgram VAD waits for a silence boundary to
    // mark the user turn final; without a tail the agent often doesn't
    // fire until ambient mic noise eventually triggers VAD seconds later.
    // 500 ms of zero PCM is enough for Deepgram's default endpointing.
    const audioBytes = base64ToBytes(clip.dataB64)
    const SILENCE_MS = 500
    const silenceLen = (SAMPLE_RATE * 2 * SILENCE_MS) / 1000 // 16 000 Hz × 2 bytes × 0.5 s = 16 000
    const playBytes = new Uint8Array(audioBytes.byteLength + silenceLen)
    playBytes.set(audioBytes, 0)
    // Trailing bytes are already 0 from `new Uint8Array(...)` — silence.

    const totalChunks = Math.ceil(playBytes.byteLength / FRAME_BYTES)
    append(
      'system',
      `▶ playing "${clip.name}" — ${(clip.durationMs / 1000).toFixed(1)}s clip + 0.5s silence (${totalChunks} chunks)`,
      'text',
    )

    let offset = 0
    let chunksSent = 0
    // Pace at FRAME_MS so STT + barge-in see the same cadence as live mic.
    const tick = () => {
      if (playbackCancelRef.current) return finish('canceled')
      if (offset >= playBytes.byteLength) return finish('done')
      const end = Math.min(offset + FRAME_BYTES, playBytes.byteLength)
      try {
        c.sendRawAudio(playBytes.subarray(offset, end))
        chunksSent += 1
      } catch (e) {
        console.warn('[voice-clip] sendRawAudio threw', e)
        return finish('error')
      }
      offset = end
    }
    const finish = (reason: 'done' | 'canceled' | 'error') => {
      if (playbackTimerRef.current !== null) {
        clearInterval(playbackTimerRef.current)
        playbackTimerRef.current = null
      }
      if (!wasMuted) c.setMicMuted?.(false)
      setPlayingClipId(null)
      const tag = reason === 'done' ? '✓ done' : reason === 'canceled' ? '⏹ canceled' : '⚠ error'
      append('system', `${tag} — sent ${chunksSent}/${totalChunks} chunks`, 'text')
    }
    playbackTimerRef.current = window.setInterval(tick, FRAME_MS)
  }

  function stopPlayback() {
    playbackCancelRef.current = true
    if (playbackTimerRef.current !== null) {
      clearInterval(playbackTimerRef.current)
      playbackTimerRef.current = null
    }
    clientRef.current?.setMicMuted?.(muted)
    setPlayingClipId(null)
  }

  function deleteClip(id: string) {
    if (playingClipId === id) stopPlayback()
    const next = clips.filter((c) => c.id !== id)
    setClips(next)
    saveClips(agentId, next)
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start() drives WS lifecycle + sets state on connect events
    start(textOnly)
    return () => {
      // Stop any in-flight clip playback so we don't leak the pacer after
      // the panel unmounts (tab swap, hangup, navigate).
      if (playbackTimerRef.current !== null) clearInterval(playbackTimerRef.current)
      clientRef.current?.hangup()
      clientRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Pin the transcript to the bottom on every append so the latest line
  // is always in view as the call streams.
  useEffect(() => {
    const el = transcriptScrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [transcript.length])

  const phase: 'connecting' | 'listening' | 'speaking' | 'closed' | 'error' =
    status === 'error'
      ? 'error'
      : status === 'closed'
        ? 'closed'
        : status === 'connecting'
          ? 'connecting'
          : agentSpeaking
            ? 'speaking'
            : 'listening'

  return (
    // In-flow surface meant to live inside the right-side inspector under a
    // tab. No fixed positioning, no backdrop — the parent decides where this
    // sits. Keeps `data-testid="test-call-modal"` for back-compat with
    // existing unit + e2e tests.
    <div
      data-testid="test-call-modal"
      className="flex h-full min-h-0 flex-1 flex-col overflow-auto bg-panel"
    >
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium">Test Call</div>
            <ActiveNodeChip node={activeNode} fallbackAgentId={agentId} />
          </div>
          <div className="flex items-center gap-2">
            <StatusPill status={status} textOnly={textOnly} />
            <button
              data-testid="test-call-close"
              onClick={() => {
                end()
                onClose()
              }}
              className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-panel-2 text-muted hover:text-fg"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        {err && (
          <div className="mx-4 mt-3 rounded-[8px] border border-red-500/40 bg-red-500/10 p-2 text-[11px] text-red-300">
            {err}
          </div>
        )}
        {ttsError && (
          <div
            data-testid="test-call-tts-error"
            className="mx-4 mt-3 rounded-[8px] border border-yellow-500/40 bg-yellow-500/10 p-2 text-[11px] text-yellow-200"
          >
            <div className="font-medium">TTS provider error: {ttsError}</div>
            <div className="text-yellow-200/70">
              The agent text below is still being generated, but audio playback
              is unavailable. Common causes: ElevenLabs quota exhausted, voice
              id revoked, or rate limit. Swap{' '}
              <code className="text-yellow-100">VOICE_ELEVENLABS_API_KEY</code>{' '}
              and restart the API to recover.
            </div>
          </div>
        )}

        {/* Big voice-state orb. Pulses when listening, glows when agent
            is speaking. This is the part that tells the user "this is a
            voice call, not a chat box". */}
        <div
          data-testid="voice-orb"
          data-phase={phase}
          className="flex flex-col items-center gap-3 px-6 py-7"
        >
          <div className="relative grid h-28 w-28 place-items-center">
            <div
              className={[
                'absolute inset-0 rounded-full',
                phase === 'speaking'
                  ? 'animate-pulse bg-accent/30'
                  : phase === 'listening' && !muted
                    ? 'animate-pulse bg-emerald-500/15'
                    : phase === 'connecting'
                      ? 'bg-yellow-500/15'
                      : 'bg-panel-2',
              ].join(' ')}
            />
            <div className="relative grid h-20 w-20 place-items-center rounded-full border border-border bg-panel-2">
              {phase === 'speaking' ? (
                <Volume2 className="h-7 w-7 text-accent" />
              ) : muted || textOnly ? (
                <MicOff className="h-7 w-7 text-muted" />
              ) : (
                <Mic
                  className={[
                    'h-7 w-7',
                    phase === 'listening' ? 'text-emerald-400' : 'text-muted',
                  ].join(' ')}
                />
              )}
            </div>
          </div>
          <div className="text-xs font-medium uppercase tracking-wider text-muted">
            {phase === 'connecting' && 'Connecting…'}
            {phase === 'listening' && (muted ? 'Mic muted' : textOnly ? 'Text mode' : 'Listening')}
            {phase === 'speaking' && 'Agent speaking'}
            {phase === 'closed' && 'Call ended'}
            {phase === 'error' && 'Call error'}
          </div>
        </div>

        {/* Slot-fill progress strip — only renders when the active node has
            a progress payload (slot_fill nodes). Lets the user see which
            fields the agent has captured without leaving the test pane. */}
        {activeFlowProgress &&
          (activeFlowProgress.filled.length > 0 || activeFlowProgress.missing.length > 0) && (
            <div
              data-testid="tc-slot-progress"
              className="flex flex-wrap items-center gap-1.5 border-t border-border bg-panel-2/30 px-4 py-2"
            >
              <span className="mr-1 text-[10px] uppercase tracking-wider text-muted">slots</span>
              {activeFlowProgress.filled.map((s) => (
                <span
                  key={`f-${s}`}
                  data-testid={`tc-slot-filled-${s}`}
                  className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[10px] text-emerald-300"
                >
                  <Check className="h-2.5 w-2.5" />
                  {s}
                </span>
              ))}
              {activeFlowProgress.missing.map((s) => (
                <span
                  key={`m-${s}`}
                  data-testid={`tc-slot-missing-${s}`}
                  className="inline-flex items-center gap-1 rounded-full border border-border bg-panel-2 px-2 py-0.5 text-[10px] text-muted"
                >
                  <CircleDashed className="h-2.5 w-2.5" />
                  {s}
                </span>
              ))}
            </div>
          )}

        {/* Live transcript — bubble layout. User right, agent left, tool
            calls + errors as distinct centered cards. Auto-scrolls on every
            new line so the latest exchange stays in view. */}
        <div
          ref={transcriptScrollRef}
          data-testid="test-call-transcript"
          className="max-h-[40vh] min-h-[160px] flex-1 overflow-auto border-t border-border bg-panel-2/40 px-3 py-3 text-xs"
        >
          {transcript.length === 0 ? (
            <div className="text-center text-muted">
              {status === 'live'
                ? 'Say something to start the conversation…'
                : status === 'connecting'
                  ? 'Connecting to the agent…'
                  : 'Call has not started.'}
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {transcript.map((l, i) => (
                <TranscriptBubble key={i} line={l} />
              ))}
            </ul>
          )}
        </div>

        {/* Voice clips. Type a phrase, click Synthesize → server-side TTS
            mints PCM16 LE @ 16 kHz mono in the agent's voice and caches
            it. Click Play to stream those bytes back into the call over
            the same WS frame format the live mic worklet uses, so STT and
            barge-in treat the clip identically to live speech. */}
        <div
          data-testid="tc-voice-clips"
          className="border-t border-border bg-panel-2/30 px-3 py-2"
        >
          <div className="mb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-muted">
            <span className="flex items-center gap-1.5">
              <Sparkles className="h-3 w-3" />
              voice clips
            </span>
            {textOnly && <span className="normal-case text-muted/60">disabled in text-only</span>}
          </div>

          {clips.length === 0 && !synthesizing && (
            <div className="mb-1.5 text-[11px] text-muted/70">
              Type a phrase and click <Sparkles className="inline h-3 w-3 text-accent" /> to
              synthesize. Clips replay byte-identical to live speech, so you can iterate on a
              flow without re-speaking every line.
            </div>
          )}

          {clips.length > 0 && (
            <ul className="mb-2 flex flex-col gap-1">
              {clips.map((clip) => {
                const playing = playingClipId === clip.id
                return (
                  <li
                    key={clip.id}
                    data-testid={`tc-clip-row-${clip.id}`}
                    className="group flex items-center gap-2 rounded-[8px] border border-border bg-panel px-2 py-1.5"
                  >
                    <button
                      data-testid={`tc-clip-play-${clip.id}`}
                      onClick={() => (playing ? stopPlayback() : playClip(clip))}
                      disabled={status !== 'live' || textOnly}
                      title={playing ? 'Stop playback' : `Play "${clip.name}" into the call`}
                      className={cn(
                        'grid h-7 w-7 shrink-0 place-items-center rounded-full border',
                        playing
                          ? 'border-accent/60 bg-accent/20 text-accent'
                          : 'border-border bg-panel-2 text-muted hover:border-accent/40 hover:text-accent',
                        'disabled:opacity-40',
                      )}
                    >
                      {playing ? <Square className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[11px] text-fg">{clip.name}</div>
                      <div className="text-[10px] text-muted/70">
                        {(clip.durationMs / 1000).toFixed(1)}s
                      </div>
                    </div>
                    <button
                      onClick={() => deleteClip(clip.id)}
                      title={`Delete "${clip.name}"`}
                      className="grid h-6 w-6 shrink-0 place-items-center rounded-[6px] text-muted/60 opacity-0 hover:text-red-300 group-hover:opacity-100"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </li>
                )
              })}
            </ul>
          )}

          {/* Synthesize control row */}
          <div className="flex items-center gap-2">
            <input
              data-testid="tc-clip-text"
              value={newClipText}
              onChange={(e) => setNewClipText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && synthesizeClip()}
              disabled={synthesizing}
              placeholder="Type a phrase to synthesize…"
              className="flex-1 rounded border border-border bg-panel-2 px-2 py-1 text-[11px] text-fg placeholder:text-muted/60 focus:outline-none disabled:opacity-60"
            />
            <button
              data-testid="tc-clip-synth"
              onClick={synthesizeClip}
              disabled={!newClipText.trim() || synthesizing || !agentVoiceId}
              title={
                !agentVoiceId
                  ? 'Agent has no voice configured'
                  : `Synthesize with the agent's voice and save as a clip`
              }
              className="inline-flex items-center gap-1 rounded-[8px] border border-accent/40 bg-accent/15 px-2 py-1 text-[11px] text-accent hover:bg-accent/25 disabled:opacity-40"
            >
              {synthesizing ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" /> Synthesizing…
                </>
              ) : (
                <>
                  <Sparkles className="h-3 w-3" /> Synthesize
                </>
              )}
            </button>
          </div>

          {synthError && (
            <div
              data-testid="tc-clip-error"
              className="mt-1.5 rounded-[6px] border border-red-500/40 bg-red-500/10 px-2 py-1 text-[10px] text-red-300"
            >
              {synthError}
            </div>
          )}
        </div>

        {/* Call controls: mute + hangup + a disclosure for the text-mode
            fallback. The fallback is intentionally tucked away so the voice
            UI doesn't read like a chat by default. */}
        <div className="flex items-center justify-between gap-3 border-t border-border p-3">
          <div className="flex items-center gap-2">
            <button
              data-testid="test-call-mute"
              onClick={toggleMute}
              disabled={status !== 'live' || textOnly}
              className={[
                'flex items-center gap-1.5 rounded-[8px] border border-border px-3 py-1.5 text-xs',
                muted
                  ? 'bg-red-500/15 text-red-300'
                  : 'bg-panel-2 text-muted hover:text-fg',
                'disabled:opacity-50',
              ].join(' ')}
            >
              {muted ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
              {muted ? 'Unmute' : 'Mute'}
            </button>
            <button
              data-testid="test-call-text-toggle"
              onClick={() => setShowText((v) => !v)}
              className="text-[11px] text-muted hover:text-fg"
            >
              {showText ? 'Hide text' : 'Type instead'}
            </button>
            <button
              data-testid="test-call-replay"
              onClick={replayLastUser}
              disabled={status !== 'live' || !lastUserText}
              title={
                lastUserText
                  ? `Replay last user message: "${lastUserText}"`
                  : 'No previous user message to replay'
              }
              className="flex items-center gap-1 rounded-[8px] border border-border bg-panel-2 px-2 py-1.5 text-[11px] text-muted hover:text-fg disabled:opacity-40"
            >
              <RotateCcw className="h-3 w-3" /> Replay
            </button>
          </div>
          <button
            onClick={() => {
              end()
              onClose()
            }}
            data-testid="test-call-end"
            className="flex items-center gap-1.5 rounded-[8px] border border-red-500/40 bg-red-500/15 px-3 py-1.5 text-xs text-red-300"
          >
            <PhoneOff className="h-3.5 w-3.5" /> Hang up
          </button>
        </div>

        {showText && (
          <div
            data-testid="test-call-text-row"
            className="flex items-center gap-2 border-t border-border p-3"
          >
            <input
              value={textInput}
              onChange={(e) => setTextInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && sendText()}
              disabled={status !== 'live'}
              placeholder="Send text alongside the voice call"
              data-testid="test-call-input"
              className="flex-1 rounded border border-border bg-panel-2 px-2 py-1.5 text-xs"
            />
            <button
              onClick={sendText}
              disabled={status !== 'live' || !textInput.trim()}
              className="flex items-center gap-1 rounded bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-50"
            >
              <Send className="h-3 w-3" /> Send
            </button>
          </div>
        )}

        {Object.keys(overrides).length > 0 && (
          <div
            data-testid="tc-overrides"
            className="border-t border-border px-4 py-2"
          >
            <div className="mb-1 text-[10px] uppercase tracking-wider text-muted">
              Dynamic variables (override per-call)
            </div>
            <ul className="flex flex-col gap-1.5">
              {Object.entries(overrides).map(([k, v]) => (
                <li key={k} className="flex items-center gap-1.5">
                  <code className="w-1/3 truncate rounded-[6px] border border-border bg-panel-2 px-2 py-1 text-[10px] text-muted">
                    {k}
                  </code>
                  <input
                    data-testid={`tc-override-${k}`}
                    value={v}
                    disabled={status === 'live'}
                    onChange={(e) =>
                      setOverrides((o) => ({ ...o, [k]: e.target.value }))
                    }
                    className="flex-1 rounded border border-border bg-panel-2 px-2 py-1 text-[11px] disabled:opacity-60"
                  />
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Text-only toggle — power-user escape hatch. Bottom-of-modal so
            it doesn't dominate the voice-first layout. */}
        <div className="border-t border-border px-4 py-2 text-[11px] text-muted">
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={textOnly}
              disabled={status === 'live'}
              onChange={(e) => setTextOnly(e.target.checked)}
            />
            text-only (skip mic + STT)
          </label>
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status, textOnly }: { status: string; textOnly: boolean }) {
  const color =
    status === 'live'
      ? 'bg-emerald-500'
      : status === 'connecting'
        ? 'bg-yellow-500'
        : status === 'error'
          ? 'bg-red-500'
          : 'bg-gray-500'
  return (
    <span
      data-testid="test-call-status"
      data-status={status}
      className="flex items-center gap-2 text-[11px] text-muted"
    >
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {status}
      {status === 'live' &&
        (textOnly ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />)}
    </span>
  )
}

type ActiveNode = {
  id: string
  data: { kind: keyof typeof KIND_TINT; title: string }
}

function ActiveNodeChip({
  node,
  fallbackAgentId,
}: {
  node: ActiveNode | null
  fallbackAgentId: string
}) {
  if (!node) {
    return <div className="text-[11px] text-muted">agent {fallbackAgentId}</div>
  }
  const Icon = KIND_ICON[node.data.kind]
  return (
    <div
      data-testid="tc-active-node"
      data-node-id={node.id}
      className="mt-0.5 inline-flex max-w-full items-center gap-1.5 truncate rounded-full border border-border bg-panel-2 px-2 py-0.5 text-[11px] text-muted"
    >
      <span className="text-[9px] uppercase tracking-wider text-muted/70">in</span>
      <Icon className={cn('h-3 w-3 shrink-0', KIND_TINT[node.data.kind])} />
      <span className="truncate text-fg">{node.data.title}</span>
    </div>
  )
}

function TranscriptBubble({ line }: { line: TranscriptLine }) {
  const time = fmtTime(line.at)

  if (line.kind === 'tool_call' || line.kind === 'tool_result') {
    return (
      <li className="flex justify-center" data-role={line.role} data-kind={line.kind}>
        <div className="w-full rounded-[10px] border border-amber-500/30 bg-amber-500/5 px-3 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-amber-300/80">
            <Wrench className="h-3 w-3" />
            {line.kind === 'tool_call' ? 'tool call' : 'tool result'}
            <span className="ml-auto font-normal normal-case tracking-normal text-muted/70">
              {time}
            </span>
          </div>
          <div
            data-testid="tc-line-text"
            className="whitespace-pre-wrap break-all font-mono text-[11px] text-amber-100/90"
          >
            {line.text}
          </div>
        </div>
      </li>
    )
  }

  if (line.kind === 'error') {
    return (
      <li className="flex justify-center" data-role={line.role} data-kind="error">
        <div className="w-full rounded-[10px] border border-red-500/40 bg-red-500/10 px-3 py-2">
          <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-red-300/80">
            <AlertCircle className="h-3 w-3" />
            error
            <span className="ml-auto font-normal normal-case tracking-normal text-muted/70">
              {time}
            </span>
          </div>
          <div
            data-testid="tc-line-text"
            className="whitespace-pre-wrap break-all font-mono text-[11px] text-red-200/90"
          >
            {line.text}
          </div>
        </div>
      </li>
    )
  }

  const isUser = line.role === 'user'
  const isAgent = line.role === 'agent'
  return (
    <li
      data-role={line.role}
      data-kind="text"
      className={cn('flex flex-col', isUser ? 'items-end' : 'items-start')}
    >
      <div
        className={cn(
          'max-w-[88%] rounded-[12px] px-3 py-1.5 text-[12px] leading-snug',
          isUser
            ? 'border border-accent/40 bg-accent/15 text-fg'
            : isAgent
              ? 'border border-border bg-panel text-fg'
              : 'bg-panel-2 text-muted italic',
        )}
      >
        <span data-testid="tc-line-text">{line.text}</span>
      </div>
      <div className={cn('mt-0.5 px-1 text-[9px] text-muted/60', isUser ? 'text-right' : '')}>
        {line.role} · {time}
      </div>
    </li>
  )
}
