import { ShieldCheck } from 'lucide-react'
import { COMPLIANCE } from './fixtures'
import { cn } from '@/lib/cn'

export function ComplianceSafety() {
  return (
    <div className="panel px-5 py-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-accent" />
          <div className="text-sm font-medium">Compliance & Safety</div>
        </div>
        <span className="text-[11px] text-muted">SOC2 · CCPA</span>
      </div>
      <ul className="grid grid-cols-2 gap-1.5">
        {COMPLIANCE.map((c) => (
          <li
            key={c.key}
            className="flex items-center justify-between rounded-[8px] border border-border bg-panel-2 px-2.5 py-1.5"
          >
            <span className="text-[11px] text-fg">{c.label}</span>
            <Dot status={c.status} />
          </li>
        ))}
      </ul>
    </div>
  )
}

function Dot({ status }: { status: 'ok' | 'warn' | 'off' }) {
  const cls = {
    ok: 'bg-accent shadow-[0_0_0_3px_var(--color-accent-soft)]',
    warn: 'bg-warn shadow-[0_0_0_3px_rgba(245,180,65,0.18)]',
    off: 'bg-muted/40',
  }[status]
  return <span className={cn('h-1.5 w-1.5 rounded-full', cls)} />
}
