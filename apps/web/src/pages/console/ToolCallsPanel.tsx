import { TOOL_CALLS, type ToolCall } from './fixtures'
import { cn } from '@/lib/cn'

export function ToolCallsPanel() {
  return (
    <div className="panel px-5 py-4" data-testid="tool-calls">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-medium">Tool Calls</div>
        <span className="text-[11px] text-muted">last 60s</span>
      </div>
      <ul className="flex flex-col gap-1">
        {TOOL_CALLS.map((t) => (
          <Row key={t.id} call={t} />
        ))}
      </ul>
    </div>
  )
}

function Row({ call }: { call: ToolCall }) {
  return (
    <li
      data-testid="tool-call-row"
      data-status={call.status}
      className="flex items-center justify-between rounded-[8px] border border-transparent px-2 py-1.5 hover:border-border hover:bg-panel-2"
    >
      <code className="font-mono text-[12px] text-fg">{call.name}</code>
      <div className="flex items-center gap-2">
        {call.ms > 0 && <span className="text-[10px] text-muted">{call.ms}ms</span>}
        <StatusPill status={call.status} />
      </div>
    </li>
  )
}

function StatusPill({ status }: { status: ToolCall['status'] }) {
  const map = {
    pending: { tint: 'text-warn bg-warn/10 border-warn/30', label: 'pending' },
    success: { tint: 'text-accent bg-accent-soft border-[color:var(--color-accent-dim)]', label: 'success' },
    failed: { tint: 'text-danger bg-danger/10 border-danger/30', label: 'failed' },
  }
  const v = map[status]
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] capitalize',
        v.tint,
      )}
    >
      <span className={cn('h-1 w-1 rounded-full', status === 'pending' && 'animate-pulse', 'bg-current')} />
      {v.label}
    </span>
  )
}
