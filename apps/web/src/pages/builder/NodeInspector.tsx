import { useEffect, useMemo, useState } from 'react'
import { Copy, Trash2 } from 'lucide-react'
import { useBuilder } from './store'
import { RULES } from './connection-rules'
import { KIND_ICON, KIND_TINT } from './icons'
import { cn } from '@/lib/cn'
import { catalog, type CatalogModel, type CatalogVoice } from '@/lib/api'
import type { RetryPolicy, StepData } from './types'

const MODEL_FALLBACK: CatalogModel[] = [
  { id: 'gemini/gemini-3.1-flash-lite', label: 'Gemini 3.1 Flash Lite', vendor: 'google', tier: 'fast' },
  { id: 'gpt-4o-mini', label: 'GPT-4o mini', vendor: 'openai', tier: 'fast' },
]
const VOICE_FALLBACK: CatalogVoice[] = [
  { id: '21m00Tcm4TlvDq8ikWAM', label: 'Rachel', vendor: 'elevenlabs', latency: 'fast' },
]

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
      className="flex w-[320px] shrink-0 flex-col border-l border-border bg-panel"
    >
      <div className="border-b border-border px-4 py-3">
        <div className="text-sm font-medium text-fg">Agent Settings</div>
        <div className="mt-0.5 text-[11px] text-muted">
          Select a node to edit its config.
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        <AgentSettingsPanel />
      </div>
    </aside>
  )
}

function AgentSettingsPanel() {
  const meta = useBuilder((s) => s.agentMeta)
  const setMeta = useBuilder((s) => s.setAgentMetaFields)
  if (!meta) {
    return (
      <div className="text-xs text-muted">
        Agent settings are unavailable in the demo seed graph. Open a real
        agent (e.g. <code>/builder/&lt;id&gt;</code>) to edit these.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-5">
      <ModelVoicePicker
        modelId={meta.modelId}
        voiceId={meta.voiceId}
        onChange={(patch) => setMeta(patch)}
      />
      <AnalysisPlanEditor
        value={meta.analysisPlan}
        onChange={(next) => setMeta({ analysisPlan: next })}
      />
      <DynamicVariablesEditor
        value={meta.dynamicVariables}
        onChange={(next) => setMeta({ dynamicVariables: next })}
      />
    </div>
  )
}

function ModelVoicePicker({
  modelId,
  voiceId,
  onChange,
}: {
  modelId: string
  voiceId: string
  onChange: (patch: { modelId?: string; voiceId?: string }) => void
}) {
  const [models, setModels] = useState<CatalogModel[]>(MODEL_FALLBACK)
  const [voices, setVoices] = useState<CatalogVoice[]>(VOICE_FALLBACK)

  useEffect(() => {
    let cancelled = false
    catalog
      .models()
      .then((m) => !cancelled && m.length && setModels(m))
      .catch(() => {})
    catalog
      .voices()
      .then((v) => !cancelled && v.length && setVoices(v))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const modelInList = models.some((m) => m.id === modelId)
  const voiceInList = voices.some((v) => v.id === voiceId)
  return (
    <section
      data-testid="agent-model-voice"
      className="flex flex-col gap-3"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
        Model &amp; Voice
      </h3>
      <Field label="LLM">
        <select
          data-testid="mv-model"
          value={modelInList ? modelId : '__custom__'}
          onChange={(e) => {
            if (e.target.value === '__custom__') return
            onChange({ modelId: e.target.value })
          }}
          className={cn(inputCls, 'appearance-none')}
        >
          {models.map((m) => (
            <option key={m.id} value={m.id} className="bg-panel">
              {m.label}
            </option>
          ))}
          {!modelInList && (
            <option value="__custom__" className="bg-panel">
              {modelId} (custom)
            </option>
          )}
        </select>
      </Field>
      <Field label="Voice (ElevenLabs)">
        <select
          data-testid="mv-voice"
          value={voiceInList ? voiceId : '__custom__'}
          onChange={(e) => {
            if (e.target.value === '__custom__') return
            onChange({ voiceId: e.target.value })
          }}
          className={cn(inputCls, 'appearance-none')}
        >
          {voices.map((v) => (
            <option key={v.id} value={v.id} className="bg-panel">
              {v.label}
            </option>
          ))}
          {!voiceInList && (
            <option value="__custom__" className="bg-panel">
              {voiceId} (custom)
            </option>
          )}
        </select>
      </Field>
    </section>
  )
}

function AnalysisPlanEditor({
  value,
  onChange,
}: {
  value: Record<string, unknown> | null
  onChange: (next: Record<string, unknown> | null) => void
}) {
  const plan = value || {}
  const summary = typeof plan.summary_prompt === 'string' ? plan.summary_prompt : ''
  const success = typeof plan.success_prompt === 'string' ? plan.success_prompt : ''
  const schemaInitial = useMemo(() => {
    const s = plan.structured_data_schema
    if (s == null) return ''
    try {
      return JSON.stringify(s, null, 2)
    } catch {
      return ''
    }
  }, [plan.structured_data_schema])
  const [schemaText, setSchemaText] = useState<string>(schemaInitial)
  const [schemaErr, setSchemaErr] = useState<string | null>(null)

  function patch(key: string, raw: unknown) {
    const next = { ...plan, [key]: raw }
    if (raw === null || raw === '' || raw === undefined) delete next[key]
    onChange(Object.keys(next).length ? next : null)
  }

  function onSchemaBlur() {
    if (!schemaText.trim()) {
      setSchemaErr(null)
      patch('structured_data_schema', null)
      return
    }
    try {
      const parsed = JSON.parse(schemaText)
      setSchemaErr(null)
      patch('structured_data_schema', parsed)
    } catch (e) {
      setSchemaErr(String(e))
    }
  }

  return (
    <section
      data-testid="agent-analysis-plan"
      className="flex flex-col gap-3"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
        Analysis Plan
      </h3>
      <Field label="Summary prompt" hint="What to summarize">
        <textarea
          data-testid="ap-summary-prompt"
          value={summary}
          rows={3}
          onChange={(e) => patch('summary_prompt', e.target.value)}
          className={inputCls}
          placeholder="Summarize the call in 2 sentences."
        />
      </Field>
      <Field label="Success prompt" hint="What counts as success">
        <textarea
          data-testid="ap-success-prompt"
          value={success}
          rows={2}
          onChange={(e) => patch('success_prompt', e.target.value)}
          className={inputCls}
          placeholder="The user booked a meeting."
        />
      </Field>
      <Field label="Structured data schema" hint="JSON Schema">
        <textarea
          data-testid="ap-structured-schema"
          value={schemaText}
          rows={5}
          onChange={(e) => setSchemaText(e.target.value)}
          onBlur={onSchemaBlur}
          className={cn(inputCls, 'font-mono')}
          placeholder='{"type":"object","properties":{"name":{"type":"string"}}}'
        />
        {schemaErr && (
          <div className="mt-1 text-[11px] text-red-400">{schemaErr}</div>
        )}
      </Field>
    </section>
  )
}

function DynamicVariablesEditor({
  value,
  onChange,
}: {
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}) {
  const entries = Object.entries(value || {})
  const [newKey, setNewKey] = useState('')
  const [newVal, setNewVal] = useState('')

  function setKey(k: string, v: string) {
    onChange({ ...(value || {}), [k]: v })
  }
  function removeKey(k: string) {
    const next = { ...(value || {}) }
    delete next[k]
    onChange(next)
  }
  function add() {
    const k = newKey.trim()
    if (!k) return
    onChange({ ...(value || {}), [k]: newVal })
    setNewKey('')
    setNewVal('')
  }

  return (
    <section
      data-testid="agent-dynamic-vars"
      className="flex flex-col gap-2"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wider text-fg">
        Dynamic Variables
      </h3>
      <p className="text-[11px] text-muted">
        Defaults injected into prompts as <code>{`{{key}}`}</code>. Test Call
        overrides take precedence per-call.
      </p>
      {entries.length === 0 ? (
        <div className="text-[11px] text-muted">No variables yet.</div>
      ) : (
        <ul className="flex flex-col gap-1.5" data-testid="dv-list">
          {entries.map(([k, v]) => (
            <li key={k} className="flex items-center gap-1.5">
              <code className="w-1/3 truncate rounded-[6px] border border-border bg-panel-2 px-2 py-1.5 text-[11px] text-muted">
                {k}
              </code>
              <input
                value={typeof v === 'string' ? v : JSON.stringify(v)}
                onChange={(e) => setKey(k, e.target.value)}
                className={cn(inputCls, 'flex-1 text-[11px]')}
              />
              <button
                onClick={() => removeKey(k)}
                title="Remove"
                className="grid h-7 w-7 place-items-center rounded-[6px] text-muted hover:text-red-400"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-1 flex items-center gap-1.5">
        <input
          data-testid="dv-new-key"
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="key"
          className={cn(inputCls, 'w-1/3 text-[11px]')}
        />
        <input
          data-testid="dv-new-val"
          value={newVal}
          onChange={(e) => setNewVal(e.target.value)}
          placeholder="value"
          className={cn(inputCls, 'flex-1 text-[11px]')}
          onKeyDown={(e) => {
            if (e.key === 'Enter') add()
          }}
        />
        <button
          data-testid="dv-add"
          onClick={add}
          className="rounded-[6px] border border-border bg-accent px-2 py-1 text-[11px] text-bg disabled:opacity-40"
          disabled={!newKey.trim()}
        >
          Add
        </button>
      </div>
    </section>
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
