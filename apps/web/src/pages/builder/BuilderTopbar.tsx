import { useEffect, useRef, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { ArrowLeft, Check, ChevronDown, Loader2, Phone, TriangleAlert, Upload } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/cn'
import { useBuilder } from './store'
import { TestCallModal } from './TestCallModal'

export function BuilderTopbar({ agentId }: { agentId: string }) {
  const agentMeta = useBuilder((s) => s.agentMeta)
  const saveStatus = useBuilder((s) => s.saveStatus)
  const saveError = useBuilder((s) => s.saveError)
  const setSaveStatus = useBuilder((s) => s.setSaveStatus)
  const setAgentMetaFields = useBuilder((s) => s.setAgentMetaFields)
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
      const detail = await api.publishAgent(agentMeta.id, {
        version_id: agentMeta.versionId,
        env: 'production',
      })
      const newDraft = [...detail.versions].sort((a, b) => b.version - a.version)[0]
      if (newDraft) {
        setAgentMetaFields({
          versionId: newDraft.id,
          versionNumber: newDraft.version,
          publishedVersionId: detail.published_version_id,
        })
      }
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
        <TestCallModal
          agentId={agentMeta.id}
          agentVariableDefaults={agentMeta.dynamicVariables}
          onClose={() => setTestCallOpen(false)}
        />
      )}
    </header>
  )
}

function SaveStatusPill({ status, error }: { status: string; error: string | null }) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- close dropdown when status leaves error
    if (status !== 'error') setOpen(false)
  }, [status])

  if (status === 'idle') return null
  const map = {
    saving: { Icon: Loader2, label: 'Saving…', cls: 'text-muted', spin: true },
    saved: { Icon: Check, label: 'Saved', cls: 'text-accent', spin: false },
    error: { Icon: TriangleAlert, label: 'Error', cls: 'text-red-400', spin: false },
  } as const
  const m = map[status as keyof typeof map] ?? map.saving
  const parsed = status === 'error' ? parseSaveError(error) : null
  const summary = parsed?.summary ?? (status === 'error' ? (error ?? 'Error') : m.label)
  const hasDropdown = status === 'error' && (parsed?.errors.length ?? 0) > 0

  if (!hasDropdown) {
    return (
      <span
        data-testid="save-status"
        data-status={status}
        title={parsed?.tooltip ?? (error ?? undefined)}
        className={cn('inline-flex items-center gap-1 text-[11px]', m.cls)}
      >
        <m.Icon className={cn('h-3 w-3', m.spin && 'animate-spin')} />
        {summary}
      </span>
    )
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        data-testid="save-status"
        data-status={status}
        data-open={open ? '1' : '0'}
        aria-expanded={open}
        aria-haspopup="listbox"
        title={parsed?.tooltip}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'inline-flex items-center gap-1 rounded-[6px] px-1 text-[11px] hover:bg-panel-2',
          m.cls,
        )}
      >
        <m.Icon className={cn('h-3 w-3', m.spin && 'animate-spin')} />
        {summary}
        <ChevronDown className={cn('h-3 w-3 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ul
          data-testid="save-error-list"
          role="listbox"
          className="absolute left-0 top-full z-50 mt-1 min-w-[280px] max-w-[420px] rounded-[8px] border border-border bg-panel-2 p-2 text-[11px] shadow-lg"
        >
          {parsed?.field && (
            <li className="px-2 pb-1 text-[10px] uppercase tracking-wider text-muted">
              {parsed.field}
            </li>
          )}
          {parsed?.errors.map((msg, i) => (
            <li
              key={`${i}-${msg}`}
              data-testid="save-error-item"
              className="rounded-[4px] px-2 py-1 text-red-400 hover:bg-panel"
            >
              {msg}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Save errors from the API are stringified `Error` objects whose message
 * carries the raw response body. Pull `detail.errors` out when present so
 * the user sees "summary_prompt must be a string" instead of a wall of JSON.
 */
function parseSaveError(
  raw: string | null,
): { summary: string; tooltip: string; errors: string[]; field?: string } | null {
  if (!raw) return null
  const match = raw.match(/\{[\s\S]*\}/)
  if (!match) return null
  try {
    const body = JSON.parse(match[0]) as {
      detail?: { errors?: string[]; field?: string }
    }
    const errors = body.detail?.errors
    if (!errors || errors.length === 0) return null
    const field = body.detail?.field
    const summary =
      errors.length === 1
        ? errors[0]
        : `${errors.length} ${field ?? ''} errors`.trim()
    return { summary, tooltip: errors.join('\n'), errors, field }
  } catch {
    return null
  }
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
