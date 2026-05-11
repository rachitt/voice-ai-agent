import { NavLink } from 'react-router-dom'
import { ArrowLeft, ChevronDown, Phone, Upload } from 'lucide-react'
import { cn } from '@/lib/cn'

export function BuilderTopbar({ agentId }: { agentId: string }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-panel px-4">
      <NavLink
        to="/"
        data-testid="back-to-console"
        className="grid h-8 w-8 place-items-center rounded-[8px] border border-border bg-bg text-muted hover:text-fg"
      >
        <ArrowLeft className="h-4 w-4" />
      </NavLink>

      <div className="flex items-center gap-2">
        <div className="text-sm font-medium">Sales Qualifier Agent</div>
        <span className="chip">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          Production
        </span>
      </div>

      <Tabs />

      <div className="ml-auto flex items-center gap-2">
        <VersionPicker />
        <button
          data-testid="test-call"
          className="inline-flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg"
        >
          <Phone className="h-3.5 w-3.5" /> Test call
        </button>
        <button
          data-testid="publish"
          className="inline-flex items-center gap-1.5 rounded-[8px] bg-accent px-3 py-1.5 text-xs font-medium text-bg hover:bg-[#3aef8d]"
        >
          <Upload className="h-3.5 w-3.5" /> Publish
        </button>
      </div>

      <span className="sr-only">{agentId}</span>
    </header>
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
            i === 0 ? 'bg-bg text-fg shadow-[inset_0_0_0_1px_var(--color-border)]' : 'text-muted hover:text-fg',
          )}
        >
          {t}
        </button>
      ))}
    </nav>
  )
}

function VersionPicker() {
  return (
    <button className="inline-flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg">
      Version 12
      <ChevronDown className="h-3.5 w-3.5" />
    </button>
  )
}
