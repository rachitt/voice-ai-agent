import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Loader2, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/cn'
import { parseApiError } from '@/lib/parseApiError'

export function SaveStatusPill({
  status,
  error,
}: {
  status: string
  error: string | null
}) {
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
  const parsed = status === 'error' ? parseApiError(error) : null
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
