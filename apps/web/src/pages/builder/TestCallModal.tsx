import { useEffect, useRef, useState } from 'react'
import { Mic, MicOff, PhoneOff, Send, Volume2, X } from 'lucide-react'
import { api, getApiBase } from '@/lib/api'
import { WebCallClient, type WebCallEvent } from '@/lib/webcall'
import { useBuilder } from './store'

type TranscriptLine = { role: 'user' | 'agent' | 'system'; text: string; at: number }

/**
 * Test Call modal.
 *
 * This is a real voice call, not a chat. By default we open a WebSocket and
 * the browser's mic streams 16-bit PCM up to the server; the agent's PCM
 * replies stream back and play through `<AudioContext>`. The text input is
 * a fallback channel — keeps the modal usable when the mic is busted, on
 * remote screens, or during deterministic QA. It's tucked behind a
 * disclosure so the UI reads as "voice first".
 *
 * Voice state derives from event timing:
 *   - "Listening"   when WS is live, agent isn't streaming text
 *   - "Agent speaking" while agent_text deltas arrive before turn_end
 *   - "Connecting" / "Closed" / "Error" — terminal states
 */
export function TestCallModal({
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
  const clientRef = useRef<WebCallClient | null>(null)
  const startedRef = useRef(false)
  const setActiveFlowNodeId = useBuilder((s) => s.setActiveFlowNodeId)

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
              data?: { node_id?: string; kind?: string }
            }
            const t = d.type
            if (t === 'flow_node' && d.data?.node_id) {
              setActiveFlowNodeId(d.data.node_id)
            } else if (t === 'tts_error') {
              const msg = (d.data as { err?: string } | undefined)?.err ?? 'tts unavailable'
              setTtsError(msg)
              setAgentSpeaking(false)
            } else if (t === 'user_text' && d.text) {
              append('user', d.text)
              setAgentSpeaking(false)
            } else if (t === 'agent_text' && d.text) {
              append('agent', d.text)
              setAgentSpeaking(true)
            } else if (t === 'turn_end') {
              setAgentSpeaking(false)
            } else if (t === 'tool_call') {
              append('system', `tool_call: ${d.text ?? ''}`)
            } else if (t === 'tool_result') {
              append('system', `tool_result: ${d.text ?? ''}`)
            } else if (t === 'error') {
              append('system', `error: ${JSON.stringify(d)}`)
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

  function append(role: 'user' | 'agent' | 'system', text: string) {
    setTranscript((t) => [...t, { role, text, at: Date.now() }])
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

  function sendText() {
    const t = textInput.trim()
    if (!t || !clientRef.current) return
    clientRef.current.sendUserText(t)
    append('user', t)
    setTextInput('')
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- start() drives WS lifecycle + sets state on connect events
    start(textOnly)
    return () => {
      clientRef.current?.hangup()
      clientRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
    // Non-modal call widget. Floats bottom-right, doesn't block the canvas,
    // so you can talk to the agent while you keep editing nodes/prompts.
    // No backdrop, no overlay — that "trap the user in a popup" UX never fit
    // a tool whose whole job is iterating on flow + listening to the agent.
    <div
      data-testid="test-call-modal"
      className="pointer-events-none fixed inset-0 z-[60]"
    >
      <div className="pointer-events-auto absolute bottom-5 right-5 w-[380px] max-w-[94vw] rounded-[16px] border border-border bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div>
            <div className="text-sm font-medium">Test Call</div>
            <div className="text-[11px] text-muted">agent {agentId}</div>
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

        {/* Live transcript — secondary surface. Renders alongside the orb so
            the user can read what STT heard + what the agent said. */}
        <div
          data-testid="test-call-transcript"
          className="max-h-[28vh] min-h-[80px] overflow-auto border-t border-border bg-panel-2/40 px-4 py-3 text-xs"
        >
          {transcript.length === 0 ? (
            <div className="text-muted">Say something to start the conversation…</div>
          ) : (
            transcript.map((l, i) => (
              <div key={i} data-role={l.role} className="mb-1.5">
                <span className="mr-2 text-[10px] uppercase text-muted">{l.role}</span>
                <span data-testid="tc-line-text">{l.text}</span>
              </div>
            ))
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
