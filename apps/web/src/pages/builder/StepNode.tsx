import { Handle, Position, type NodeProps } from '@xyflow/react'
import { cn } from '@/lib/cn'
import { RULES } from './connection-rules'
import { KIND_ICON, KIND_TINT } from './icons'
import type { StepNode as TStepNode } from './types'

const HANDLE_BASE =
  '!h-3 !w-3 !border-2 !border-bg !bg-border-strong transition-all hover:!h-4 hover:!w-4 hover:!bg-accent'
const HANDLE_DISABLED = '!h-3 !w-3 !border-2 !border-bg !bg-border opacity-40 cursor-not-allowed'

export function StepNodeView({ id, data, selected }: NodeProps<TStepNode>) {
  const Icon = KIND_ICON[data.kind]
  const rule = RULES[data.kind]
  const canTarget = rule.inAllowed
  const canSource = rule.outMax > 0 && !rule.terminal
  return (
    <div
      data-testid="step-node"
      data-node-id={id}
      data-kind={data.kind}
      data-selected={selected ? '1' : '0'}
      className={cn(
        'group relative w-[220px] rounded-[12px] border bg-panel shadow-[0_8px_24px_-12px_rgba(0,0,0,0.6)] transition-all',
        selected ? 'border-accent shadow-[0_0_0_1px_var(--color-accent)]' : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={canTarget}
        data-testid={`handle-target-${id}`}
        title={canTarget ? 'Drop a connection here' : `${data.kind} cannot receive inbound edges`}
        className={canTarget ? HANDLE_BASE : HANDLE_DISABLED}
      />
      <div className="flex items-center gap-2 px-3 pb-1 pt-3">
        <div className="grid h-7 w-7 place-items-center rounded-[8px] bg-panel-2 border border-border">
          <Icon className={cn('h-3.5 w-3.5', KIND_TINT[data.kind])} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium leading-tight">{data.title}</div>
          <div className="truncate text-[11px] text-muted">{data.kind}</div>
        </div>
      </div>
      <div className="px-3 pb-3 pt-1">
        <p className="line-clamp-2 text-[12px] text-muted">{data.subtitle ?? data.prompt ?? '…'}</p>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={canSource}
        data-testid={`handle-source-${id}`}
        title={
          canSource
            ? rule.outNeedsLabel
              ? `Drag to add a branch (${(rule.allowedLabels ?? []).join('/')})`
              : 'Drag to connect to next step'
            : `${data.kind} has no outbound edges`
        }
        className={canSource ? HANDLE_BASE : HANDLE_DISABLED}
      />
    </div>
  )
}
