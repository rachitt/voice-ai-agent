import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ArrowLeft, Check, Loader2, Phone, TriangleAlert, Upload } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useBuilder } from './store'
import { TestCallModal } from './TestCallModal'

export function BuilderTopbar({ agentId }: { agentId: string }) {
  const agentMeta = useBuilder((s) => s.agentMeta)
  const saveStatus = useBuilder((s) => s.saveStatus)
  const saveError = useBuilder((s) => s.saveError)
  const setSaveStatus = useBuilder((s) => s.setSaveStatus)
  const [publishErrors, setPublishErrors] = useState<string[] | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [testCallOpen, setTestCallOpen] = useState(false)

  const name = agentMeta?.name ?? (agentId === 'demo' ? 'Sales Qualifier Agent' : 'Loading…')
  const versionLabel = agentMeta ? `Version ${agentMeta.versionNumber}` : 'Version —'
  const envLabel = agentMeta?.publishedVersionId === agentMeta?.versionId ? 'Production' : 'Draft'

  async function onPublish() {
    if (!agentMeta) return
    setPublishErrors(null)
    setPublishing(true)
    try {
      await api.publishAgent(agentMeta.id, { version_id: agentMeta.versionId, env: 'production' })
      setSaveStatus('saved')
    } catch (e) {
      const msg = String(e)
      // Try parse our 422 {errors,warnings} payload from the message body.
      const m = msg.match(/\{[\s\S]*\}/)
      if (m) {
        try {
          const body = JSON.parse(m[0])
          if (body?.detail?.errors) {
            setPublishErrors(body.detail.errors as string[])
            return
          }
        } catch {
          // fall through
        }
      }
      setPublishErrors([msg])
    } finally {
      setPublishing(false)
    }
  }

  return (
    <header className="relative flex h-14 shrink-0 items-center gap-4 border-b border-border bg-panel px-4">
      <NavLink
        to="/"
        data-testid="back-to-console"
        className="grid h-8 w-8 place-items-center rounded-[8px] border border-border bg-bg text-muted hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" />
      </NavLink>

      <div className="flex items-center gap-2">
        <div data-testid="builder-agent-name" className="text-sm font-medium">
          {name}
        </div>
        <span className="chip" data-testid="builder-env-chip">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          {envLabel}
        </span>
        <SaveStatusPill status={saveStatus} error={saveError} />
      </div>

      <Tabs />

      <div className="ml-auto flex items-center gap-2">
        <button
          data-testid="version-picker"
          className="inline-flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          {versionLabel}
        </button>
        <button
          data-testid="test-call"
          onClick={() => agentMeta && setTestCallOpen(true)}
          disabled={!agentMeta}
          title={agentMeta ? 'Open a live test call' : 'Save the agent first'}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg',
            !agentMeta && 'opacity-60 cursor-not-allowed',
          )}
        >
          <Phone className="h-3.5 w-3.5" /> Test call
        </button>
        <button
          data-testid="publish"
          onClick={onPublish}
          disabled={publishing || !agentMeta}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-[8px] bg-accent px-3 py-1.5 text-xs font-medium text-bg hover:bg-[#3aef8d]',
            (publishing || !agentMeta) && 'opacity-60 cursor-not-allowed',
          )}
        >
          <Upload className="h-3.5 w-3.5" /> {publishing ? 'Publishing…' : 'Publish'}
        </button>
      </div>

      {publishErrors && publishErrors.length > 0 && (
        <div
          role="alert"
          data-testid="publish-errors"
          className="absolute left-1/2 top-[58px] z-40 w-[420px] -translate-x-1/2 rounded-[10px] border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-300 shadow-2xl"
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="font-medium">Cannot publish — fix:</span>
            <button onClick={() => setPublishErrors(null)} className="text-red-300/70 hover:text-red-200">
              ✕
            </button>
          </div>
          <ul className="list-disc space-y-0.5 pl-4">
            {publishErrors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <span className="sr-only">{agentId}</span>

      {testCallOpen && agentMeta && (
        <TestCallModal agentId={agentMeta.id} onClose={() => setTestCallOpen(false)} />
      )}
    </header>
  )
}

function SaveStatusPill({ status, error }: { status: string; error: string | null }) {
  if (status === 'idle') return null
  const map = {
    saving: { Icon: Loader2, label: 'Saving…', cls: 'text-muted', spin: true },
    saved: { Icon: Check, label: 'Saved', cls: 'text-accent', spin: false },
    error: { Icon: TriangleAlert, label: error ?? 'Error', cls: 'text-red-400', spin: false },
  } as const
  const m = map[status as keyof typeof map] ?? map.saving
  return (
    <span
      data-testid="save-status"
      data-status={status}
      title={error ?? undefined}
      className={cn('inline-flex items-center gap-1 text-[11px]', m.cls)}
    >
      <m.Icon className={cn('h-3 w-3', m.spin && 'animate-spin')} />
      {m.label}
    </span>
  )
}

function Tabs() {
  return (
    <nav className="ml-2 flex items-center gap-1 rounded-[10px] border border-border bg-panel-2 p-1">
      {['Builder', 'Logs'].map((t, i) => (
        <button
          key={t}
          className={cn(
            'rounded-[8px] px-3 py-1 text-xs transition-colors',
            i === 0
              ? 'bg-bg text-fg shadow-[inset_0_0_0_1px_var(--color-border)]'
              : 'text-muted hover:text-fg',
          )}
        >
          {t}
        </button>
      ))}
    </nav>
  )
}
