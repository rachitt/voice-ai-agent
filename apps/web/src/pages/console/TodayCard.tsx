import { TrendingDown, TrendingUp } from 'lucide-react'
import { useConsoleSummary } from './useSummary'

export function TodayCard() {
  const { data } = useConsoleSummary()
  const t = data?.today
  const calls = t?.calls ?? 0
  const completed = t?.completed ?? 0
  const failed = t?.failed ?? 0
  const avgSec = t ? Math.round(t.avg_duration_ms / 1000) : 0
  const delta = t?.calls_delta_vs_yesterday ?? 0
  const successPct = calls > 0 ? Math.round((completed / calls) * 100) : 0

  return (
    <div className="panel px-5 py-4" data-testid="today">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Today</div>
        {!data && (
          <span className="chip" data-testid="today-demo">
            demo
          </span>
        )}
      </div>

      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-2xl font-medium tracking-tight" data-testid="today-calls">
          {calls}
        </span>
        <span className="text-xs text-muted">calls</span>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
        {delta >= 0 ? (
          <TrendingUp className="h-3 w-3 text-accent" />
        ) : (
          <TrendingDown className="h-3 w-3 text-warn" />
        )}
        <span className={delta >= 0 ? 'text-accent' : 'text-warn'}>
          {delta > 0 ? '+' : ''}
          {delta}
        </span>
        <span>vs yesterday</span>
        <span className="mx-1 text-border-strong">·</span>
        <span>avg {avgSec}s</span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
        <Stat label="Completed" value={completed} tone="ok" />
        <Stat label="Failed" value={failed} tone={failed ? 'warn' : 'muted'} />
        <Stat label="Success" value={`${successPct}%`} tone="ok" />
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: number | string
  tone: 'ok' | 'warn' | 'muted'
}) {
  return (
    <div className="rounded-[8px] border border-border bg-panel-2 px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div
        className={
          tone === 'ok'
            ? 'text-fg'
            : tone === 'warn'
              ? 'text-warn'
              : 'text-muted'
        }
      >
        {value}
      </div>
    </div>
  )
}
