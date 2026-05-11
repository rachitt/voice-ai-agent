import { History } from 'lucide-react'
import { LAUNCH_HISTORY } from './fixtures'
import { useConsoleSummary } from './useSummary'
import { cn } from '@/lib/cn'

const STATUS_TINT = {
  live: 'text-accent border-[color:var(--color-accent-dim)] bg-accent-soft',
  archived: 'text-muted border-border bg-panel-2',
  'rolled-back': 'text-danger border-danger/30 bg-danger/10',
} as const

export function LaunchHistory() {
  const { data } = useConsoleSummary()
  const items =
    (data?.launch_history as typeof LAUNCH_HISTORY | undefined) ?? LAUNCH_HISTORY
  return (
    <div className="panel px-5 py-4" data-testid="launch-history">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <History className="h-4 w-4 text-muted" />
          <div className="text-sm font-medium">Launch History</div>
          {!data && (
            <span className="chip" data-testid="launch-history-demo">
              demo
            </span>
          )}
        </div>
        <button className="text-[11px] text-muted hover:text-fg">All →</button>
      </div>
      <ul className="flex flex-col">
        {items.length === 0 ? (
          <li className="py-2 text-[11px] text-muted">No launches yet.</li>
        ) : null}
        {items.map((h, i) => (
          <li
            key={h.id}
            className={cn(
              'flex items-center justify-between py-2',
              i !== 0 && 'border-t border-border',
            )}
          >
            <div>
              <div className="text-[12px]">{h.date}</div>
              <div className="text-[10px] text-muted">{h.env} · {h.version}</div>
            </div>
            <span
              className={cn(
                'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] capitalize',
                STATUS_TINT[h.status],
              )}
            >
              {h.status}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
