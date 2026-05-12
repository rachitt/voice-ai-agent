import { useCallback, useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BarChart3, RefreshCw } from 'lucide-react'
import { analytics, type AnalyticsResponse } from '@/lib/api'
import { cn } from '@/lib/cn'

type Range = '7d' | '30d' | '90d'

export function AnalyticsPage() {
  const [range, setRange] = useState<Range>('7d')
  const [data, setData] = useState<AnalyticsResponse | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      setData(await analytics.get(range))
    } catch (e) {
      setErr(String(e))
    } finally {
      setLoading(false)
    }
  }, [range])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch-on-deps; load() sets state after async resolve
    void load()
  }, [load])

  return (
    <div className="flex flex-col gap-4" data-testid="analytics-root">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="h-4 w-4 text-muted" />
          <h1 className="text-sm font-medium">Analytics</h1>
        </div>
        <div className="flex items-center gap-2">
          <RangePicker value={range} onChange={setRange} />
          <button
            onClick={load}
            className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
            title="Refresh"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          </button>
        </div>
      </header>

      {err && (
        <div className="panel bg-danger/10 px-5 py-2 text-xs text-danger">{err}</div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total calls" value={data ? String(data.total_calls) : '—'} />
        <Stat
          label="Success rate"
          value={data ? `${Math.round(data.success_rate * 100)}%` : '—'}
        />
        <Stat
          label="Avg duration"
          value={data ? fmtDuration(data.avg_duration_ms) : '—'}
        />
        <Stat
          label="p95 duration"
          value={data ? fmtDuration(data.p95_duration_ms) : '—'}
        />
      </div>

      <section className="panel p-4">
        <h2 className="mb-3 text-xs uppercase tracking-wide text-muted">
          Call volume
        </h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data?.volume_by_day || []}
              margin={{ top: 8, right: 12, bottom: 0, left: -16 }}
            >
              <CartesianGrid stroke="#1f2725" strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 10, fill: '#8a9590' }}
                tickFormatter={(d: string) => d.slice(5)}
              />
              <YAxis tick={{ fontSize: 10, fill: '#8a9590' }} allowDecimals={false} />
              <Tooltip
                contentStyle={{
                  background: '#111614',
                  border: '1px solid #2a3330',
                  fontSize: 11,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                type="monotone"
                dataKey="completed"
                stroke="#22e07a"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="failed"
                stroke="#e05a5a"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 text-xs uppercase tracking-wide text-muted">
          Top agents
        </h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={(data?.by_agent || []).map((a) => ({
                ...a,
                success_pct: Math.round(a.success_rate * 100),
              }))}
              margin={{ top: 8, right: 12, bottom: 0, left: -16 }}
            >
              <CartesianGrid stroke="#1f2725" strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#8a9590' }} />
              <YAxis
                yAxisId="count"
                tick={{ fontSize: 10, fill: '#8a9590' }}
                allowDecimals={false}
              />
              <YAxis
                yAxisId="pct"
                orientation="right"
                tick={{ fontSize: 10, fill: '#8a9590' }}
                domain={[0, 100]}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{
                  background: '#111614',
                  border: '1px solid #2a3330',
                  fontSize: 11,
                }}
                formatter={(v, name) => {
                  return name === 'success_pct' ? `${v}%` : String(v)
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="count" dataKey="count" fill="#22e07a" name="calls" />
              <Bar yAxisId="pct" dataKey="success_pct" fill="#1a9a55" name="success_pct" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </div>
  )
}

function RangePicker({
  value,
  onChange,
}: {
  value: Range
  onChange: (v: Range) => void
}) {
  const opts: Range[] = ['7d', '30d', '90d']
  return (
    <div className="flex items-center rounded-[8px] border border-border bg-panel-2 p-0.5">
      {opts.map((o) => (
        <button
          key={o}
          data-testid={`range-${o}`}
          onClick={() => onChange(o)}
          className={cn(
            'rounded-[6px] px-2.5 py-1 text-xs transition-colors',
            value === o
              ? 'bg-accent text-bg'
              : 'text-muted hover:text-fg',
          )}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-lg font-medium text-fg">{value}</div>
    </div>
  )
}

function fmtDuration(ms: number): string {
  if (!ms) return '0s'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  return rem ? `${m}m ${rem}s` : `${m}m`
}
