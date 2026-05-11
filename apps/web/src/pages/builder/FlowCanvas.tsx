import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useRef } from 'react'
import { StepNodeView } from './StepNode'
import { useBuilder } from './store'
import type { StepKind, StepNode } from './types'

const nodeTypes = { step: StepNodeView }

export function FlowCanvas() {
  return (
    <ReactFlowProvider>
      <InnerCanvas />
    </ReactFlowProvider>
  )
}

function InnerCanvas() {
  const { nodes, edges, onNodesChange, onEdgesChange, onConnect, setSelected, addNode } =
    useBuilder()
  const wrapper = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition } = useReactFlow()

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const kind = e.dataTransfer.getData('application/voice-step') as StepKind | ''
      if (!kind) return
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY })
      addNode(kind as StepKind, position)
    },
    [addNode, screenToFlowPosition],
  )

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  return (
    <div ref={wrapper} className="relative min-h-0 flex-1 bg-bg">
      <ReactFlow<StepNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_e, n: Node) => setSelected(n.id)}
        onPaneClick={() => setSelected(null)}
        onDrop={onDrop}
        onDragOver={onDragOver}
        defaultEdgeOptions={{
          type: 'smoothstep',
          style: { stroke: 'var(--color-border-strong)', strokeWidth: 1.5 },
        }}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          color="#26302d"
          gap={20}
          size={1.4}
        />
        <Controls
          className="!rounded-[10px] !border !border-border !bg-panel"
          showInteractive={false}
        />
      </ReactFlow>
    </div>
  )
}
