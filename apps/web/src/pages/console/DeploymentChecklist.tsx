import { Check, Sparkles, Phone, BookOpen, AudioLines, Shield, Wrench, Rocket } from 'lucide-react'
import { CHECKLIST, type ChecklistStep } from './fixtures'
import { useConsoleSummary } from './useSummary'
import { cn } from '@/lib/cn'

const ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  phone: Phone,
  kb: BookOpen,
  voice: AudioLines,
  guardrails: Shield,
  tools: Wrench,
  launch: Rocket,
}

export function DeploymentChecklist() {
  const { data } = useConsoleSummary()
  const steps: ChecklistStep[] = (data?.checklist as ChecklistStep[] | undefined) ?? CHECKLIST
  return (
    <div className="panel px-5 py-4" data-testid="checklist">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <div className="text-sm font-medium">Deployment Checklist</div>
          {!data && (
            <span className="chip" data-testid="checklist-demo">
              demo
            </span>
          )}
        </div>
        <button className="text-xs text-accent hover:underline">View runbook</button>
      </div>

      <ol className="grid grid-cols-6 gap-1">
        {steps.map((s, i) => (
          <Step key={s.key} step={s} isLast={i === steps.length - 1} />
        ))}
      </ol>
    </div>
  )
}

function Step({ step, isLast }: { step: ChecklistStep; isLast: boolean }) {
  const Icon = ICON[step.key]
  return (
    <li
      className="relative flex flex-col items-center"
      data-testid={`checklist-step-${step.key}`}
      data-status={step.status}
    >
      {!isLast && (
        <span
          className={cn(
            'absolute left-1/2 top-5 h-px w-full',
            step.status === 'done' ? 'bg-accent-dim' : 'bg-border',
          )}
        />
      )}
      <div
        className={cn(
          'relative z-10 grid h-10 w-10 place-items-center rounded-full border-2 transition-colors',
          step.status === 'done' &&
            'border-accent bg-accent text-bg',
          step.status === 'current' &&
            'border-accent bg-accent-soft text-accent shadow-[0_0_0_4px_var(--color-accent-soft)]',
          step.status === 'todo' && 'border-border bg-panel-2 text-muted',
        )}
      >
        {step.status === 'done' ? (
          <Check className="h-4 w-4" strokeWidth={3} />
        ) : (
          <Icon className="h-4 w-4" />
        )}
      </div>
      <div className="mt-2 text-center">
        <div
          className={cn(
            'text-[11px] font-medium',
            step.status === 'todo' ? 'text-muted' : 'text-fg',
          )}
        >
          {step.label}
        </div>
        {step.status === 'current' && (
          <div className="mt-0.5 inline-flex items-center gap-1 text-[10px] text-accent">
            <span className="h-1 w-1 animate-pulse rounded-full bg-accent" />
            in progress
          </div>
        )}
      </div>
    </li>
  )
}
