import { TrendingDown, TrendingUp } from 'lucide-react'

export function TodayCard() {
  return (
    <div className="panel px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Today</div>
        <button className="text-[11px] text-muted hover:text-fg">Monthly ↓</button>
      </div>

      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-2xl font-medium tracking-tight">$46</span>
        <span className="text-muted">–</span>
        <span className="text-2xl font-medium tracking-tight">$68</span>
      </div>
      <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
        <TrendingDown className="h-3 w-3 text-accent" />
        <span className="text-accent">–22%</span>
        <span>vs yesterday</span>
        <span className="mx-1 text-border-strong">·</span>
        <TrendingUp className="h-3 w-3" />
        480 minutes
      </div>

      <div className="mt-3 flex items-center justify-between rounded-[8px] border border-border bg-panel-2 px-3 py-2 text-[11px]">
        <span className="text-muted">Cost breakdown</span>
        <span className="font-mono text-fg">STT · LLM · TTS · PSTN</span>
      </div>
    </div>
  )
}
