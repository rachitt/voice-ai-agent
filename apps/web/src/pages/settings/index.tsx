import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calendar, CheckCircle2, Copy, Key, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { apiKeys, getApiBase, integrations, type ApiKeyRow, type IntegrationStatus } from '@/lib/api'
import { useAuth } from '@/lib/useAuth'
import { ApiErrorBanner } from '@/components/ApiErrorBanner'

export function SettingsPage() {
  const { loading, signedIn } = useAuth()
  if (loading) return <Loading />
  if (!signedIn) return <SignedOut />
  return (
    <div className="flex flex-col gap-6" data-testid="settings-root">
      <IntegrationsSection />
      <ApiKeysSection />
    </div>
  )
}

function IntegrationsSection() {
  const [status, setStatus] = useState<IntegrationStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [params, setParams] = useSearchParams()
  const justConnected = params.get('connected') === 'google_calendar'
  const oauthError = params.get('error')

  const load = useCallback(async () => {
    setErr(null)
    try {
      setStatus(await integrations.googleCalendarStatus())
    } catch (e) {
      setErr(String(e))
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot mount fetch
    void load()
  }, [load])

  useEffect(() => {
    if (justConnected || oauthError) {
      // Clean the URL after acknowledging the redirect — keeps state idempotent.
      const next = new URLSearchParams(params)
      next.delete('connected')
      next.delete('error')
      setParams(next, { replace: true })
    }
  }, [justConnected, oauthError, params, setParams])

  const connect = () => {
    // Full-page redirect — survives the round-trip + lets Google plant the
    // session-state cookie correctly. Cross-origin (api ≠ web) requires
    // same-site=lax cookies, which window.location.assign respects.
    window.location.assign(`${getApiBase()}/v1/integrations/google/calendar/connect`)
  }

  const disconnect = async () => {
    setBusy(true)
    setErr(null)
    try {
      await integrations.disconnectGoogleCalendar()
      await load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel p-5" data-testid="integrations-section">
      <header className="mb-4 flex items-center gap-3">
        <Calendar className="h-4 w-4 text-accent" />
        <h2 className="text-sm font-medium">Integrations</h2>
      </header>
      <ApiErrorBanner err={err} />
      {justConnected && (
        <div className="mb-3 rounded-[8px] border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-200">
          Google Calendar connected. Your `book_meeting` tool now writes to this account.
        </div>
      )}
      {oauthError && (
        <div className="mb-3 rounded-[8px] border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] text-red-200">
          OAuth failed: {oauthError}
        </div>
      )}

      <div
        className="flex items-center justify-between rounded-[8px] border border-border bg-panel-2 p-3"
        data-testid="integration-google-calendar"
      >
        <div className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-[8px] border border-border bg-bg">
            <Calendar className="h-4 w-4 text-muted" />
          </div>
          <div>
            <div className="text-[13px] font-medium">Google Calendar</div>
            <div className="text-[11px] text-muted">
              {status?.connected ? (
                <span className="inline-flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                  Connected as {status.account_email}
                </span>
              ) : (
                'Connect to let agents book meetings on your calendar.'
              )}
            </div>
          </div>
        </div>
        {status?.connected ? (
          <button
            type="button"
            data-testid="disconnect-google-calendar"
            onClick={disconnect}
            disabled={busy}
            className="rounded-[8px] border border-border bg-panel px-3 py-1.5 text-[12px] text-muted hover:border-red-500/40 hover:text-red-300 disabled:opacity-50"
          >
            {busy ? 'Disconnecting…' : 'Disconnect'}
          </button>
        ) : (
          <button
            type="button"
            data-testid="connect-google-calendar"
            onClick={connect}
            className="rounded-[8px] border border-accent bg-accent-soft px-3 py-1.5 text-[12px] text-fg hover:bg-accent-soft/80"
          >
            Connect
          </button>
        )}
      </div>
    </section>
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

      <ApiErrorBanner err={err} variant="stripe" />

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
