import { useState } from 'react'
import { Phone, SlidersHorizontal } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useBuilder } from './store'
import { NodeInspector } from './NodeInspector'
import { TestCallPanel } from './TestCallPanel'

type Tab = 'node' | 'test'

export function RightPanel() {
  const testCallAgentId = useBuilder((s) => s.testCallAgentId)
  if (!testCallAgentId) return <NodeInspector />
  // Force a fresh mount when the active call changes so the inner state
  // (tab selection, transcript ref, etc.) starts clean for the new agent.
  return <RightPanelWithCall key={testCallAgentId} testCallAgentId={testCallAgentId} />
}

function RightPanelWithCall({ testCallAgentId }: { testCallAgentId: string }) {
  const closeTestCall = useBuilder((s) => s.closeTestCall)
  const dynamicVariables = useBuilder((s) => s.agentMeta?.dynamicVariables)
  // Default to the Test Call tab — pressing Test Call should land you on it.
  // User can flip to Node anytime; the call keeps streaming behind the tab.
  const [tab, setTab] = useState<Tab>('test')

  return (
    <aside
      data-testid="right-panel"
      className="flex w-[400px] shrink-0 flex-col border-l border-border bg-panel"
    >
      <div
        role="tablist"
        className="flex shrink-0 items-center gap-1 border-b border-border bg-panel-2/40 px-2 py-1.5"
      >
        <TabButton
          active={tab === 'node'}
          onClick={() => setTab('node')}
          testId="right-tab-node"
          icon={<SlidersHorizontal className="h-3.5 w-3.5" />}
          label="Node"
        />
        <TabButton
          active={tab === 'test'}
          onClick={() => setTab('test')}
          testId="right-tab-test"
          icon={<Phone className="h-3.5 w-3.5" />}
          label="Test Call"
          dotColor="bg-emerald-500"
        />
      </div>

      {/* Both panes stay mounted; we hide the inactive one so the test call
          WebSocket survives a flip back to the Node tab for editing. */}
      <div className="flex min-h-0 flex-1 flex-col" hidden={tab !== 'node'}>
        <NodeInspector bare />
      </div>
      <div className="flex min-h-0 flex-1 flex-col" hidden={tab !== 'test'}>
        <TestCallPanel
          agentId={testCallAgentId}
          agentVariableDefaults={dynamicVariables}
          onClose={closeTestCall}
        />
      </div>
    </aside>
  )
}

function TabButton({
  active,
  onClick,
  testId,
  icon,
  label,
  dotColor,
}: {
  active: boolean
  onClick: () => void
  testId: string
  icon: React.ReactNode
  label: string
  dotColor?: string
}) {
  return (
    <button
      role="tab"
      aria-selected={active}
      data-testid={testId}
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-[8px] px-3 py-1.5 text-xs',
        active
          ? 'bg-bg text-fg shadow-[inset_0_0_0_1px_var(--color-border)]'
          : 'text-muted hover:text-fg',
      )}
    >
      {icon}
      {label}
      {dotColor && <span className={cn('ml-1 h-1.5 w-1.5 rounded-full', dotColor)} />}
    </button>
  )
}
