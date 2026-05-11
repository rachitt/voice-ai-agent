import { Handle, Position, type NodeProps } from '@xyflow/react'
import { cn } from '@/lib/cn'
import { KIND_ICON, KIND_TINT } from './icons'
import type { StepNode as TStepNode } from './types'

export function StepNodeView({ data, selected }: NodeProps<TStepNode>) {
  const Icon = KIND_ICON[data.kind]
  return (
    <div
      className={cn(
        'group relative w-[220px] rounded-[12px] border bg-panel shadow-[0_8px_24px_-12px_rgba(0,0,0,0.6)] transition-all',
        selected ? 'border-accent shadow-[0_0_0_1px_var(--color-accent)]' : 'border-border',
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !border-0 !bg-border-strong"
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
        className="!h-2 !w-2 !border-0 !bg-border-strong"
      />
    </div>
  )
}
