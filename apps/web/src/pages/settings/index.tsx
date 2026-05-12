import { useCallback, useEffect, useState } from 'react'
import { Copy, Key, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { apiKeys, type ApiKeyRow } from '@/lib/api'
import { useAuth } from '@/lib/useAuth'

export function SettingsPage() {
  const { loading, signedIn } = useAuth()
  if (loading) return <Loading />
  if (!signedIn) return <SignedOut />
  return (
    <div className="flex flex-col gap-6" data-testid="settings-root">
      <ApiKeysSection />
    </div>
  )
}

function Loading() {
  return <div className="text-sm text-muted">Loading…</div>
}

function SignedOut() {
  return (
    <div className="panel p-6 text-sm text-muted">
      Sign in to manage settings.
    </div>
  )
}

function ApiKeysSection() {
  const [rows, setRows] = useState<ApiKeyRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [revealed, setRevealed] = useState<{ id: string; key: string } | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const list = (await apiKeys.list()) ?? []
      setRows(list)
    } catch (e) {
      setErr(String(e))
      setRows([])
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial API keys fetch on mount
    load()
  }, [load])

  async function onCreate() {
    if (!newName.trim()) return
    setBusy(true)
    setErr(null)
    try {
      const created = await apiKeys.create(newName.trim())
      if (created) setRevealed({ id: created.id, key: created.key })
      setNewName('')
      setShowNew(false)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onRevoke(id: string) {
    if (!confirm('Revoke this key? Apps using it will stop working immediately.')) return
    setBusy(true)
    setErr(null)
    try {
      await apiKeys.revoke(id)
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel" data-testid="api-keys-section">
      <header className="flex items-center justify-between border-b border-border px-5 py-4">
        <div className="flex items-center gap-2">
          <Key className="h-4 w-4 text-muted" />
          <h2 className="text-sm font-medium">API Keys</h2>
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
            data-testid="new-api-key"
            onClick={() => setShowNew(true)}
            className="flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs hover:bg-bg"
          >
            <Plus className="h-3.5 w-3.5" /> New key
          </button>
        </div>
      </header>

      {err && (
        <div className="border-b border-border bg-danger/10 px-5 py-2 text-xs text-danger">
          {err}
        </div>
      )}

      {revealed && (
        <RevealedKey
          rawKey={revealed.key}
          onDismiss={() => setRevealed(null)}
        />
      )}

      {showNew && (
        <div className="flex items-center gap-2 border-b border-border bg-panel-2 px-5 py-3">
          <input
            data-testid="new-api-key-name"
            autoFocus
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Key name (e.g. production-api)"
            className="flex-1 rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs text-fg outline-none focus:border-accent"
            onKeyDown={(e) => {
              if (e.key === 'Enter') onCreate()
              if (e.key === 'Escape') {
                setShowNew(false)
                setNewName('')
              }
            }}
          />
          <button
            data-testid="confirm-new-key"
            disabled={busy || !newName.trim()}
            onClick={onCreate}
            className="rounded-[6px] bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-40"
          >
            Create
          </button>
          <button
            onClick={() => {
              setShowNew(false)
              setNewName('')
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
          No API keys yet. Mint one to use with the SDK.
        </div>
      ) : (
        <ul className="divide-y divide-border" data-testid="api-keys-list">
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate font-medium">{r.name}</span>
                  {r.revoked_at && (
                    <span className="chip text-danger">revoked</span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
                  <code className="font-mono">{r.prefix}…</code>
                  <span>
                    {r.last_used_at
                      ? `last used ${relTime(r.last_used_at)}`
                      : 'never used'}
                  </span>
                  <span>created {relTime(r.created_at)}</span>
                </div>
              </div>
              {!r.revoked_at && (
                <button
                  data-testid={`revoke-${r.id}`}
                  disabled={busy}
                  onClick={() => onRevoke(r.id)}
                  className="grid h-7 w-7 place-items-center rounded-[6px] text-muted hover:text-danger"
                  title="Revoke"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RevealedKey({ rawKey, onDismiss }: { rawKey: string; onDismiss: () => void }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(rawKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // noop
    }
  }
  return (
    <div
      data-testid="revealed-key"
      className="flex items-center gap-3 border-b border-border bg-accent-soft px-5 py-3"
    >
      <div className="min-w-0 flex-1">
        <div className="text-xs text-fg">
          Copy this key now — you won't see it again.
        </div>
        <code
          data-testid="revealed-key-value"
          className="mt-1 block truncate font-mono text-xs"
        >
          {rawKey}
        </code>
      </div>
      <button
        onClick={copy}
        className="flex items-center gap-1.5 rounded-[6px] border border-border bg-panel px-3 py-1.5 text-xs"
      >
        <Copy className="h-3.5 w-3.5" /> {copied ? 'Copied' : 'Copy'}
      </button>
      <button
        onClick={onDismiss}
        className="rounded-[6px] border border-border bg-panel px-3 py-1.5 text-xs text-muted hover:text-fg"
      >
        Done
      </button>
    </div>
  )
}

function relTime(iso: string): string {
  const d = new Date(iso)
  const diff = Date.now() - d.getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const days = Math.floor(h / 24)
  return `${days}d ago`
}
