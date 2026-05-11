import { useBuilder } from './store'
import { RULES, remainingLabels } from './connection-rules'

export function BranchLabelDialog() {
  const pending = useBuilder((s) => s.pendingBranchConnect)
  const nodes = useBuilder((s) => s.nodes)
  const edges = useBuilder((s) => s.edges)
  const commit = useBuilder((s) => s.commitBranchConnect)
  const cancel = useBuilder((s) => s.setPendingBranchConnect)

  if (!pending || !pending.source) return null

  const src = nodes.find((n) => n.id === pending.source)
  if (!src) return null
  const rule = RULES[src.data.kind]
  const allowed = rule.allowedLabels ?? []
  const remaining = remainingLabels(src.id, nodes, edges)
  const target = nodes.find((n) => n.id === pending.target)

  return (
    <div
      data-testid="branch-dialog"
      className="absolute inset-0 z-50 grid place-items-center bg-bg/70 backdrop-blur-sm"
    >
      <div className="w-[320px] rounded-[12px] border border-border bg-panel p-4 shadow-2xl">
        <div className="mb-1 text-sm font-medium">Pick branch label</div>
        <div className="mb-3 text-xs text-muted">
          {src.data.title} → {target?.data.title ?? pending.target}
        </div>
        <div className="mb-3 flex gap-2">
          {allowed.map((label) => {
            const available = remaining.includes(label)
            return (
              <button
                key={label}
                type="button"
                data-testid={`branch-label-${label}`}
                disabled={!available}
                onClick={() => commit(label)}
                className={
                  available
                    ? 'flex-1 rounded-[8px] border border-border bg-panel-2 px-3 py-2 text-xs capitalize text-fg hover:border-accent hover:bg-accent-soft'
                    : 'flex-1 rounded-[8px] border border-border bg-panel-2 px-3 py-2 text-xs capitalize text-muted opacity-40 cursor-not-allowed'
                }
              >
                {label}
              </button>
            )
          })}
        </div>
        <div className="flex justify-end">
          <button
            type="button"
            data-testid="branch-cancel"
            onClick={() => cancel(null)}
            className="rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
