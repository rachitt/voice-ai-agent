import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Mic, MicOff, PhoneOff, Send, X } from 'lucide-react'
import { api, getApiBase, getApiKey } from '@/lib/api'
import { WebCallClient, type WebCallEvent } from '@/lib/webcall'

type TranscriptLine = { role: 'user' | 'agent' | 'system'; text: string; at: number }

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
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const [textOnly, setTextOnly] = useState(false)
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

  async function start(useTextOnly: boolean) {
    if (startedRef.current) return
    startedRef.current = true
    if (!getApiKey()) {
      setStatus('error')
      setErr('API key not set. Visit /web-call to add one.')
      return
    }
    try {
      const created = await api.createWebCall(agentId, overrides)
      try {
        localStorage.setItem('voice2.watch_call_id', created.id)
      } catch {
        // ignore (private mode)
      }
      const c = new WebCallClient({
        wsUrl: created.ws_url,
        textOnly: useTextOnly,
        onEvent: (e: WebCallEvent) => {
          if (e.type === 'open') setStatus('live')
          if (e.type === 'close') setStatus('closed')
          if (e.type === 'error') {
            setStatus('error')
            setErr(e.error)
          }
          if (e.type === 'server') {
            const d = e.data as { type?: string; text?: string }
            const t = d.type
            if (t === 'user_text' && d.text) append('user', d.text)
            else if (t === 'agent_text' && d.text) append('agent', d.text)
            else if (t === 'tool_call') append('system', `tool_call: ${d.text ?? ''}`)
            else if (t === 'tool_result') append('system', `tool_result: ${d.text ?? ''}`)
            else if (t === 'error') append('system', `error: ${JSON.stringify(d)}`)
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

  return (
    <div
      data-testid="test-call-modal"
      className="fixed inset-0 z-[60] grid place-items-center bg-bg/80 backdrop-blur-sm"
    >
      <div className="w-[520px] max-w-[92vw] rounded-[14px] border border-border bg-panel shadow-2xl">
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
            {err.includes('API key') && (
              <>
                {' '}
                <Link to="/web-call" className="underline">
                  open creds
                </Link>
              </>
            )}
          </div>
        )}

        <div className="border-b border-border px-4 py-2 text-[11px] text-muted">
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

        {Object.keys(overrides).length > 0 && (
          <div
            data-testid="tc-overrides"
            className="border-b border-border px-4 py-2"
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

        <div
          data-testid="test-call-transcript"
          className="max-h-[40vh] min-h-[20vh] overflow-auto px-4 py-3 text-xs"
        >
          {transcript.length === 0 ? (
            <div className="text-muted">No transcript yet.</div>
          ) : (
            transcript.map((l, i) => (
              <div key={i} className="mb-1.5">
                <span className="mr-2 text-[10px] uppercase text-muted">{l.role}</span>
                <span>{l.text}</span>
              </div>
            ))
          )}
        </div>

        <div className="flex items-center gap-2 border-t border-border p-3">
          <input
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendText()}
            disabled={status !== 'live'}
            placeholder="Type a message (text mode)"
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
          <button
            onClick={end}
            disabled={status !== 'live'}
            data-testid="test-call-end"
            className="flex items-center gap-1 rounded border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs text-red-300 disabled:opacity-50"
          >
            <PhoneOff className="h-3 w-3" /> End
          </button>
        </div>
      </div>
    </div>
  )
}

function StatusPill({ status, textOnly }: { status: string; textOnly: boolean }) {
  const color =
    status === 'live'
      ? 'bg-green-500'
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
