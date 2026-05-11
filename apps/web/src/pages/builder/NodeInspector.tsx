import { Copy, Trash2 } from 'lucide-react'
import { useBuilder } from './store'
import { RULES } from './connection-rules'
import { KIND_ICON, KIND_TINT } from './icons'
import { cn } from '@/lib/cn'
import type { RetryPolicy, StepData } from './types'

const TAB_KEYS = ['Settings', 'Transitions'] as const
type Tab = (typeof TAB_KEYS)[number]

export function NodeInspector() {
  const node = useBuilder((s) => s.nodes.find((n) => n.id === s.selectedId)) ?? null
  const edges = useBuilder((s) => s.edges)
  const update = useBuilder((s) => s.updateNodeData)
  const removeNode = useBuilder((s) => s.removeNode)
  const duplicateNode = useBuilder((s) => s.duplicateNode)

  if (!node) return <EmptyInspector />

  const set = (patch: Partial<StepData>) => update(node.id, patch)
  const Icon = KIND_ICON[node.data.kind]
  const rule = RULES[node.data.kind]
  const inboundCount = edges.filter((e) => e.target === node.id).length
  const outboundCount = edges.filter((e) => e.source === node.id).length

  return (
    <aside
      data-testid="inspector"
      data-node-id={node.id}
      className="flex w-[320px] shrink-0 flex-col border-l border-border bg-panel"
    >
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <div className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-panel-2">
          <Icon className={cn('h-3.5 w-3.5', KIND_TINT[node.data.kind])} />
        </div>
        <div className="min-w-0 flex-1">
          <div
            data-testid="inspector-title"
            className="truncate text-sm font-medium"
          >
            {node.data.title}
          </div>
          <div className="text-[11px] text-muted">{node.id}</div>
        </div>
        <button
          type="button"
          data-testid="inspector-duplicate"
          title="Duplicate node"
          onClick={() => duplicateNode(node.id)}
          className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-panel-2 text-muted hover:text-fg"
        >
          <Copy className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          data-testid="inspector-delete"
          title="Delete node"
          onClick={() => removeNode(node.id)}
          className="grid h-7 w-7 place-items-center rounded-[8px] border border-border bg-panel-2 text-muted hover:border-red-500/40 hover:text-red-400"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>

      <Tabs />

      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4">
        <Field label="Title">
          <input
            data-testid="title-input"
            className={inputCls}
            value={node.data.title}
            onChange={(e) => set({ title: e.target.value })}
            placeholder="Step title"
          />
        </Field>

        <Field label="Connections">
          <div
            data-testid="conn-summary"
            className="flex items-center justify-between rounded-[8px] border border-border bg-panel-2 px-2.5 py-1.5 text-[12px] text-muted"
          >
            <span>
              in: <span className="text-fg">{inboundCount}</span>
              {!rule.inAllowed && <span className="ml-1 text-[10px] text-muted/70">(none allowed)</span>}
            </span>
            <span>
              out: <span className="text-fg">{outboundCount}</span>
              <span className="ml-1 text-[10px] text-muted/70">/ max {rule.outMax}</span>
            </span>
          </div>
          {rule.outNeedsLabel && outboundCount < rule.outMax && (
            <div
              data-testid="conn-hint-branch"
              className="mt-1.5 rounded-[8px] border border-yellow-500/30 bg-yellow-500/10 px-2.5 py-1.5 text-[11px] text-yellow-300/90"
            >
              Add {rule.outMax - outboundCount} more branch
              {rule.outMax - outboundCount === 1 ? '' : 'es'} to complete the condition
              {rule.allowedLabels ? ` (${rule.allowedLabels.join('/')})` : ''}.
            </div>
          )}
        </Field>

        <Field label="Voice">
          <Select
            value={node.data.voice ?? 'Aria Power'}
            onChange={(v) => set({ voice: v })}
            options={['Aria Power', 'Atlas Calm', 'Nova Bright', 'Lyra Soft']}
          />
        </Field>

        <Field label="Mode">
          <Select
            value={node.data.mode ?? 'Normal'}
            onChange={(v) => set({ mode: v as StepData['mode'] })}
            options={['Normal', 'Strict', 'Creative']}
          />
        </Field>

        <Field label="Prompt">
          <textarea
            rows={4}
            data-testid="prompt-input"
            className={inputCls}
            value={node.data.prompt ?? ''}
            onChange={(e) => set({ prompt: e.target.value, subtitle: e.target.value })}
            placeholder="What's your voice agent's job here?"
          />
        </Field>

        {node.data.kind === 'kb_lookup' && (
          <>
            <Field label="Knowledge base ID" hint="Defaults to first bound KB">
              <input
                data-testid="kb-id-input"
                className={inputCls}
                value={node.data.kb_id ?? ''}
                onChange={(e) => set({ kb_id: e.target.value })}
                placeholder="kb_abc123"
              />
            </Field>
            <Field label="Query template" hint="Liquid-style {{variables}} OK">
              <textarea
                rows={2}
                data-testid="kb-query-input"
                className={inputCls}
                value={node.data.query_template ?? ''}
                onChange={(e) => set({ query_template: e.target.value })}
                placeholder="What does the caller want to know about {{topic}}?"
              />
            </Field>
            <Field label="Top K" hint="1–20">
              <input
                type="number"
                min={1}
                max={20}
                data-testid="kb-topk-input"
                className={inputCls}
                value={node.data.top_k ?? 5}
                onChange={(e) => set({ top_k: Math.max(1, Math.min(20, Number(e.target.value) || 5)) })}
              />
            </Field>
          </>
        )}

        <Field label="Interruption handling" hint="Allow caller to interrupt mid-utterance">
          <Select
            value={node.data.interruption ?? 'allow'}
            onChange={(v) => set({ interruption: v as StepData['interruption'] })}
            options={['allow', 'block', 'soft']}
          />
        </Field>

        <Field label="Webhook">
          <input
            className={inputCls}
            value={node.data.webhook ?? ''}
            onChange={(e) => set({ webhook: e.target.value })}
            placeholder="https://hooks.acme.com/…"
          />
        </Field>

        <Field label="Retry policy">
          <div className="flex gap-2">
            {(['none', 'linear', 'exponential'] as RetryPolicy[]).map((r) => (
              <button
                key={r}
                onClick={() => set({ retry: r })}
                data-testid={`retry-${r}`}
                data-active={node.data.retry === r ? '1' : '0'}
                className={cn(
                  'flex-1 rounded-[8px] border px-2 py-1.5 text-[11px] capitalize transition-colors',
                  node.data.retry === r
                    ? 'border-accent bg-accent-soft text-fg'
                    : 'border-border text-muted hover:text-fg',
                )}
              >
                {r}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Sample response">
          <code className="block rounded-[8px] border border-border bg-panel-2 px-2 py-1.5 font-mono text-[11px] text-muted">
            {node.data.sample ?? '—'}
          </code>
        </Field>
      </div>
    </aside>
  )
}

function EmptyInspector() {
  return (
    <aside
      data-testid="inspector-empty"
      className="flex w-[320px] shrink-0 items-center justify-center border-l border-border bg-panel text-xs text-muted"
    >
      Select a node
    </aside>
  )
}

function Tabs() {
  return (
    <div className="flex gap-1 border-b border-border px-3 pt-2">
      {TAB_KEYS.map((t, i) => (
        <TabBtn key={t} label={t} active={i === 0} />
      ))}
    </div>
  )
}

function TabBtn({ label, active }: { label: Tab; active: boolean }) {
  return (
    <button
      className={cn(
        'relative px-3 py-2 text-xs transition-colors',
        active ? 'text-fg' : 'text-muted hover:text-fg',
      )}
    >
      {label}
      {active && (
        <span className="absolute inset-x-2 -bottom-px h-px bg-accent" />
      )}
    </button>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted">
          {label}
        </label>
        {hint && <span className="text-[10px] text-muted/70">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

const inputCls =
  'w-full resize-none rounded-[8px] border border-border bg-panel-2 px-2.5 py-1.5 text-[12px] text-fg outline-none placeholder:text-muted/70 focus:border-accent-dim'

function Select({
  value,
  onChange,
  options,
}: {
  value: string
  onChange: (v: string) => void
  options: string[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={cn(inputCls, 'appearance-none capitalize')}
    >
      {options.map((o) => (
        <option key={o} value={o} className="bg-panel">
          {o}
        </option>
      ))}
    </select>
  )
}
