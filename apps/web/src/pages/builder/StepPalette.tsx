import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { PALETTE } from './palette'
import { KIND_ICON } from './icons'
import { cn } from '@/lib/cn'

export function StepPalette() {
  const [q, setQ] = useState('')
  const filtered = useMemo(
    () => PALETTE.filter((p) => p.title.toLowerCase().includes(q.toLowerCase())),
    [q],
  )
  const core = filtered.filter((p) => p.group === 'core')
  const integ = filtered.filter((p) => p.group === 'integrations')

  return (
    <aside
      data-testid="palette"
      className="flex w-[240px] shrink-0 flex-col border-r border-border bg-panel"
    >
      <div className="px-4 py-4">
        <div className="text-sm font-medium">Add Step</div>
      </div>
      <div className="px-3 pb-3">
        <div className="flex items-center gap-2 rounded-[8px] border border-border bg-panel-2 px-2 py-1.5">
          <Search className="h-3.5 w-3.5 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search"
            data-testid="palette-search"
            className="w-full bg-transparent text-xs outline-none placeholder:text-muted"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto px-2 pb-3">
        <Group title="Core Blocks">
          {core.map((p) => (
            <PaletteRow key={p.kind} kind={p.kind} title={p.title} subtitle={p.subtitle} />
          ))}
        </Group>
        <Group title="Integrations">
          {integ.map((p) => (
            <PaletteRow key={p.kind} kind={p.kind} title={p.title} subtitle={p.subtitle} />
          ))}
        </Group>
      </div>
    </aside>
  )
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 first:mt-0">
      <div className="px-2 pb-1.5 text-[10px] uppercase tracking-wider text-muted">{title}</div>
      <div className="flex flex-col gap-1">{children}</div>
    </div>
  )
}

const REAL_KINDS = new Set([
  'greeting',
  'collect',
  'api',
  'condition',
  'transfer',
  'voicemail',
  'end',
])

function PaletteRow({
  kind,
  title,
  subtitle,
}: {
  kind: keyof typeof KIND_ICON
  title: string
  subtitle: string
}) {
  const Icon = KIND_ICON[kind]
  const isReal = REAL_KINDS.has(kind)
  return (
    <button
      type="button"
      draggable={isReal}
      data-testid={`palette-row-${kind}`}
      data-kind={kind}
      title={isReal ? 'Click or drag to add' : 'Integration — coming soon'}
      onClick={() => {
        if (!isReal) return
        window.dispatchEvent(new CustomEvent('voice:add-step', { detail: { kind } }))
      }}
      onDragStart={(e) => {
        if (!isReal) {
          e.preventDefault()
          return
        }
        e.dataTransfer.setData('application/voice-step', String(kind))
        e.dataTransfer.effectAllowed = 'move'
      }}
      className={cn(
        'flex w-full cursor-grab items-center gap-2 rounded-[8px] border border-transparent px-2 py-1.5 text-left',
        'hover:border-border hover:bg-panel-2 active:cursor-grabbing',
        !isReal && 'opacity-50 cursor-not-allowed',
      )}
    >
      <div className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-bg">
        <Icon className="h-3.5 w-3.5 text-muted" />
      </div>
      <div className="min-w-0">
        <div className="text-[12px] leading-tight">{title}</div>
        <div className="truncate text-[11px] text-muted">{subtitle}</div>
      </div>
    </button>
  )
}
