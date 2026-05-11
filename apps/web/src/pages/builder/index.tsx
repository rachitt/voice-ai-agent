import { useParams } from 'react-router-dom'
import { BuilderTopbar } from './BuilderTopbar'
import { StepPalette } from './StepPalette'
import { FlowCanvas } from './FlowCanvas'
import { NodeInspector } from './NodeInspector'

export function BuilderPage() {
  const { agentId = 'demo' } = useParams()
  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden bg-bg text-fg">
      <BuilderTopbar agentId={agentId} />
      <div className="flex min-h-0 flex-1">
        <StepPalette />
        <FlowCanvas />
        <NodeInspector />
      </div>
    </div>
  )
}
