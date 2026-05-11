import { useEffect, useRef, useState } from 'react'
import { Mic, MicOff, Phone, PhoneOff, Send } from 'lucide-react'

import {
  API_BASE_KEY,
  API_KEY_KEY,
  api,
  getApiBase,
  getApiKey,
  setApiBase,
  setApiKey,
  type AgentSummary,
} from '@/lib/api'
import { WebCallClient, type WebCallEvent } from '@/lib/webcall'

type TranscriptLine = { role: 'user' | 'agent' | 'system'; text: string; at: number }

export function WebCallPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [selected, setSelected] = useState<string>('')
  const [apiBase, setApiBaseLocal] = useState(getApiBase())
  const [apiKey, setApiKeyLocal] = useState(getApiKey())
  const [status, setStatus] = useState<'idle' | 'connecting' | 'live' | 'closed'>('idle')
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const [textInput, setTextInput] = useState('')
  const [textOnly, setTextOnly] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const clientRef = useRef<WebCallClient | null>(null)

  useEffect(() => {
    setApiBase(apiBase)
    setApiKey(apiKey)
  }, [apiBase, apiKey])

  async function loadAgents() {
    setErr(null)
    try {
      const a = await api.listAgents()
      setAgents(a)
      if (!selected && a.length > 0) setSelected(a[0].id)
    } catch (e) {
      setErr(String(e))
    }
  }

  function append(line: TranscriptLine) {
    setTranscript((t) => [...t, line])
  }

  async function startCall() {
    if (!selected) {
      setErr('Pick an agent first')
      return
    }
    setStatus('connecting')
    setErr(null)
    setTranscript([])
    try {
      const created = await api.createWebCall(selected)
      const c = new WebCallClient({
        wsUrl: created.ws_url,
        textOnly,
        onEvent: (e: WebCallEvent) => {
          if (e.type === 'open') setStatus('live')
          if (e.type === 'close') setStatus('closed')
          if (e.type === 'error') setErr(e.error)
          if (e.type === 'server') {
            const d = e.data as { type?: string; text?: string }
            const t = d.type
            if (t === 'user_text' && d.text) append({ role: 'user', text: d.text, at: Date.now() })
            else if (t === 'agent_text' && d.text) append({ role: 'agent', text: d.text, at: Date.now() })
            else if (t === 'tool_call')
              append({ role: 'system', text: `tool_call: ${d.text}`, at: Date.now() })
            else if (t === 'tool_result')
              append({ role: 'system', text: `tool_result: ${d.text}`, at: Date.now() })
            else if (t === 'turn_end') {
              /* no-op marker */
            } else if (t === 'error')
              append({ role: 'system', text: `error: ${JSON.stringify(d)}`, at: Date.now() })
          }
        },
      })
      clientRef.current = c
      await c.connect({ apiBase })
    } catch (e) {
      setErr(String(e))
      setStatus('idle')
    }
  }

  function endCall() {
    clientRef.current?.hangup()
    clientRef.current = null
    setStatus('closed')
  }

  function sendText() {
    const t = textInput.trim()
    if (!t || !clientRef.current) return
    clientRef.current.sendUserText(t)
    append({ role: 'user', text: t, at: Date.now() })
    setTextInput('')
  }

  return (
    <div className="mx-auto max-w-3xl p-6 text-sm">
      <h1 className="mb-4 text-xl font-semibold">Web Call (browser)</h1>

      <section className="mb-4 rounded-md border border-border bg-panel p-4">
        <div className="mb-3 grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted">API base</span>
            <input
              className="rounded border border-border bg-panel-2 px-2 py-1.5"
              value={apiBase}
              onChange={(e) => setApiBaseLocal(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted">API key</span>
            <input
              type="password"
              className="rounded border border-border bg-panel-2 px-2 py-1.5"
              value={apiKey}
              onChange={(e) => setApiKeyLocal(e.target.value)}
              placeholder="sk_live_..."
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadAgents}
            className="rounded border border-border bg-panel-2 px-3 py-1.5 text-xs hover:bg-panel"
          >
            Load agents
          </button>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="flex-1 rounded border border-border bg-panel-2 px-2 py-1.5 text-xs"
          >
            <option value="">— pick an agent —</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.id.slice(0, 12)}…)
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1 text-xs text-muted">
            <input
              type="checkbox"
              checked={textOnly}
              onChange={(e) => setTextOnly(e.target.checked)}
            />
            text-only
          </label>
        </div>
      </section>

      <section className="mb-4 flex items-center gap-3">
        {status === 'live' ? (
          <button
            onClick={endCall}
            className="flex items-center gap-2 rounded bg-red-500 px-4 py-2 text-white hover:bg-red-600"
          >
            <PhoneOff className="h-4 w-4" /> End
          </button>
        ) : (
          <button
            onClick={startCall}
            disabled={!selected || !apiKey || status === 'connecting'}
            className="flex items-center gap-2 rounded bg-accent px-4 py-2 text-bg hover:opacity-90 disabled:opacity-50"
          >
            <Phone className="h-4 w-4" /> Start call
          </button>
        )}
        <StatusPill status={status} textOnly={textOnly} />
      </section>

      {err && <div className="mb-3 rounded border border-red-500 bg-red-500/10 p-2 text-xs text-red-300">{err}</div>}

      <section className="rounded-md border border-border bg-panel">
        <div className="border-b border-border px-4 py-2 text-xs uppercase tracking-wider text-muted">
          Transcript
        </div>
        <div className="max-h-[40vh] min-h-[20vh] overflow-auto p-3">
          {transcript.length === 0 ? (
            <div className="text-xs text-muted">Nothing yet.</div>
          ) : (
            transcript.map((l, i) => (
              <div key={i} className="mb-1.5">
                <span className="mr-2 text-[10px] uppercase text-muted">{l.role}</span>
                <span>{l.text}</span>
              </div>
            ))
          )}
        </div>
        <div className="flex gap-2 border-t border-border p-2">
          <input
            value={textInput}
            onChange={(e) => setTextInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendText()}
            disabled={status !== 'live'}
            placeholder="Type message (text mode)"
            className="flex-1 rounded border border-border bg-panel-2 px-2 py-1.5 text-xs"
          />
          <button
            onClick={sendText}
            disabled={status !== 'live'}
            className="flex items-center gap-1 rounded bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-50"
          >
            <Send className="h-3 w-3" /> Send
          </button>
        </div>
      </section>
    </div>
  )
}

function StatusPill({ status, textOnly }: { status: string; textOnly: boolean }) {
  const color =
    status === 'live'
      ? 'bg-green-500'
      : status === 'connecting'
        ? 'bg-yellow-500'
        : status === 'closed'
          ? 'bg-gray-500'
          : 'bg-gray-700'
  return (
    <span className="flex items-center gap-2 text-xs text-muted">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {status}
      {status === 'live' &&
        (textOnly ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />)}
    </span>
  )
}

export default WebCallPage

// Avoid unused — kept for callers
void API_BASE_KEY
void API_KEY_KEY
