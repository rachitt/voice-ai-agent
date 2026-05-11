import { NavLink } from 'react-router-dom'
import { Settings2 } from 'lucide-react'
import { DeploymentChecklist } from './DeploymentChecklist'
import { LiveCallSimulator } from './LiveCallSimulator'
import { LiveTranscript } from './LiveTranscript'
import { ToolCallsPanel } from './ToolCallsPanel'
import { TodayCard } from './TodayCard'
import { RealtimeScoreGauge } from './RealtimeScoreGauge'
import { ComplianceSafety } from './ComplianceSafety'
import { LaunchHistory } from './LaunchHistory'

export function ConsolePage() {
  return (
    <div className="flex flex-col gap-4">
      <DeploymentChecklist />

      <div className="grid grid-cols-12 gap-4">
        <section className="col-span-12 xl:col-span-8 grid grid-cols-12 gap-4">
          <div className="col-span-12 md:col-span-5">
            <LiveCallSimulator />
          </div>
          <div className="col-span-12 md:col-span-7 flex flex-col gap-4">
            <LiveTranscript />
            <ToolCallsPanel />
          </div>
        </section>

        <aside className="col-span-12 xl:col-span-4 flex flex-col gap-4">
          <TodayCard />
          <RealtimeScoreGauge />
          <ComplianceSafety />
          <LaunchHistory />
        </aside>
      </div>

      <div className="panel flex items-center justify-between px-5 py-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          <Settings2 className="h-3.5 w-3.5" />
          Need to change a step? Edit your agent in the visual builder.
        </div>
        <NavLink
          to="/builder/demo"
          className="rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-fg hover:bg-bg"
        >
          Open Builder →
        </NavLink>
      </div>
    </div>
  )
}
