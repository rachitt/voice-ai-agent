import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, RefreshCw } from 'lucide-react'
import { api, type AgentSummary } from '@/lib/api'

/**
 * Console panel that lists the signed-in org's agents and lets the user
 * spawn a new one. Auth is owned by Shell/AuthGate — by the time this
 * renders, the session cookie is known-good, so we just call the API.
 */
export function AgentsListPanel() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<AgentSummary[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')

  async function load() {
    setErr(null)
    setLoading(true)
    try {
      const a = await api.listAgents()
      setAgents(a)
    } catch (e) {
      setErr(String(e))
      setAgents([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    load()
  }, [])

  async function createAgent() {
    const name = newName.trim()
    if (!name) return
    setErr(null)
    try {
      const detail = await api.createAgent({
        name,
        first_message: 'Hi! How can I help today?',
        system_prompt: 'You are a helpful voice agent.',
      })
      setCreating(false)
      setNewName('')
      navigate(`/builder/${detail.id}`)
    } catch (e) {
      setErr(String(e))
    }
  }

  return (
    <section className="panel p-4" data-testid="agents-panel">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium">My Agents</div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            data-testid="agents-refresh"
            className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-panel-2 text-muted hover:text-fg"
            title="Refresh"
          >
            <RefreshCw className={loading ? 'h-3.5 w-3.5 animate-spin' : 'h-3.5 w-3.5'} />
          </button>
          <button
            data-testid="agents-new"
            onClick={() => setCreating((v) => !v)}
            className="inline-flex items-center gap-1 rounded-[8px] bg-accent px-3 py-1.5 text-xs text-bg"
          >
            <Plus className="h-3.5 w-3.5" /> New
          </button>
        </div>
      </div>

      {creating && (
        <div className="mb-3 flex items-center gap-2" data-testid="agents-new-form">
          <input
            data-testid="agents-new-name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && createAgent()}
            placeholder="Agent name"
            className="flex-1 rounded border border-border bg-panel-2 px-2 py-1.5 text-xs"
          />
          <button
            onClick={createAgent}
            data-testid="agents-new-save"
            className="rounded-[8px] bg-accent px-3 py-1.5 text-xs text-bg"
          >
            Create
          </button>
        </div>
      )}

      {err && (
        <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-300">
          {err}
        </div>
      )}

      {!agents ? (
        <div className="text-xs text-muted">Loading…</div>
      ) : agents.length === 0 ? (
        <div className="text-xs text-muted" data-testid="agents-empty">
          No agents yet. Click <span className="text-fg">New</span> to create one.
        </div>
      ) : (
        <ul className="flex flex-col gap-1" data-testid="agents-list">
          {agents.map((a) => (
            <li key={a.id}>
              <button
                data-testid={`agent-row-${a.id}`}
                onClick={() => navigate(`/builder/${a.id}`)}
                className="flex w-full items-center justify-between rounded-[8px] border border-border bg-panel-2 px-3 py-2 text-left hover:border-accent"
              >
                <div className="min-w-0">
                  <div className="truncate text-[12px] font-medium">{a.name}</div>
                  <div className="truncate text-[11px] text-muted">{a.id}</div>
                </div>
                <div className="text-[11px] text-muted">
                  {a.published_version_id ? 'published' : 'draft'}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
