import { useCallback, useEffect, useState } from 'react'
import { Copy, Phone, Plus, RefreshCw } from 'lucide-react'
import {
  api,
  phoneNumbers,
  type AgentSummary,
  type PhoneNumber,
} from '@/lib/api'
import { cn } from '@/lib/cn'
import { ApiErrorBanner } from '@/components/ApiErrorBanner'

export function NumbersPage() {
  const [rows, setRows] = useState<PhoneNumber[] | null>(null)
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [newE164, setNewE164] = useState('+1')
  const [newAgent, setNewAgent] = useState<string>('')
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const [list, ags] = await Promise.all([
        phoneNumbers.list(),
        api.listAgents().catch(() => [] as AgentSummary[]),
      ])
      setRows(list)
      setAgents(ags)
    } catch (e) {
      setErr(String(e))
      setRows([])
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial numbers fetch on mount
    void load()
  }, [load])

  async function onCreate() {
    if (!/^\+[1-9]\d{6,14}$/.test(newE164)) {
      setErr('E.164 format required, e.g. +14155551234')
      return
    }
    setBusy(true)
    setErr(null)
    try {
      await phoneNumbers.create({
        e164: newE164,
        agent_id: newAgent || null,
      })
      setNewE164('+1')
      setNewAgent('')
      setShowNew(false)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onBindAgent(id: string, agentId: string) {
    setBusy(true)
    setErr(null)
    try {
      await phoneNumbers.update(id, { agent_id: agentId || null })
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onToggleStatus(row: PhoneNumber) {
    const next = row.status === 'active' ? 'disabled' : 'active'
    setBusy(true)
    setErr(null)
    try {
      await phoneNumbers.update(row.id, { status: next })
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function copy(id: string, e164: string) {
    try {
      await navigator.clipboard.writeText(e164)
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 1200)
    } catch {
      // noop
    }
  }

  return (
    <div className="flex flex-col gap-6" data-testid="numbers-root">
      <section className="panel">
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 text-muted" />
            <h2 className="text-sm font-medium">Phone Numbers</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              data-testid="new-number"
              onClick={() => setShowNew(true)}
              className="flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs hover:bg-bg"
            >
              <Plus className="h-3.5 w-3.5" /> New number
            </button>
          </div>
        </header>

        <ApiErrorBanner err={err} variant="stripe" />

        {showNew && (
          <div className="flex flex-wrap items-center gap-2 border-b border-border bg-panel-2 px-5 py-3">
            <input
              data-testid="new-number-e164"
              autoFocus
              value={newE164}
              onChange={(e) => setNewE164(e.target.value)}
              placeholder="+14155551234"
              className="w-44 rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs font-mono outline-none focus:border-accent"
            />
            <select
              value={newAgent}
              onChange={(e) => setNewAgent(e.target.value)}
              className="rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
            >
              <option value="">(no agent)</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <button
              data-testid="confirm-new-number"
              disabled={busy}
              onClick={onCreate}
              className="rounded-[6px] bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-40"
            >
              Create
            </button>
            <button
              onClick={() => {
                setShowNew(false)
                setNewE164('+1')
                setNewAgent('')
              }}
              className="rounded-[6px] border border-border bg-bg px-3 py-1.5 text-xs text-muted hover:text-fg"
            >
              Cancel
            </button>
          </div>
        )}

        {rows === null ? (
          <div className="px-5 py-8 text-sm text-muted">Loading…</div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-8 text-sm text-muted">
            No phone numbers yet. Add one to start receiving calls.
          </div>
        ) : (
          <ul className="divide-y divide-border" data-testid="numbers-list">
            {rows.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm"
              >
                <div className="flex min-w-0 flex-1 items-center gap-3">
                  <code className="font-mono text-fg">{r.e164}</code>
                  <button
                    onClick={() => copy(r.id, r.e164)}
                    className="grid h-6 w-6 place-items-center rounded-[6px] text-muted hover:text-fg"
                    title="Copy"
                  >
                    <Copy className="h-3 w-3" />
                  </button>
                  {copiedId === r.id && (
                    <span className="text-[11px] text-accent">copied</span>
                  )}
                  <span className="text-[11px] text-muted">{r.provider}</span>
                </div>

                <select
                  data-testid={`bind-${r.id}`}
                  value={r.agent_id || ''}
                  disabled={busy}
                  onChange={(e) => onBindAgent(r.id, e.target.value)}
                  className="rounded-[6px] border border-border bg-bg px-2 py-1 text-xs outline-none focus:border-accent"
                >
                  <option value="">(no agent)</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </select>

                <button
                  data-testid={`status-${r.id}`}
                  disabled={busy}
                  onClick={() => onToggleStatus(r)}
                  className={cn(
                    'chip cursor-pointer',
                    r.status === 'active'
                      ? 'text-accent'
                      : 'text-muted',
                  )}
                  title="Toggle status"
                >
                  {r.status}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
