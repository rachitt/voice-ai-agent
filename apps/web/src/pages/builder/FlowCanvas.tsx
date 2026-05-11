import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useCallback, useEffect, useRef } from 'react'
import { BranchLabelDialog } from './BranchLabelDialog'
import { canConnect } from './connection-rules'
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
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setSelected,
    addNode,
    connectionError,
    setConnectionError,
  } = useBuilder()
  const wrapper = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition } = useReactFlow()

  const isValidConnection = useCallback(
    (c: Connection | Edge) => {
      const check = canConnect(c.source, c.target, nodes, edges)
      return check.ok
    },
    [nodes, edges],
  )

  useEffect(() => {
    if (!connectionError) return
    const t = setTimeout(() => setConnectionError(null), 3500)
    return () => clearTimeout(t)
  }, [connectionError, setConnectionError])

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

  useEffect(() => {
    function handler(e: Event) {
      const kind = (e as CustomEvent<{ kind: StepKind }>).detail?.kind
      if (!kind || !wrapper.current) return
      const rect = wrapper.current.getBoundingClientRect()
      const position = screenToFlowPosition({
        x: rect.left + rect.width / 2,
        y: rect.top + rect.height / 2,
      })
      addNode(kind, position)
    }
    window.addEventListener('voice:add-step', handler as EventListener)
    return () => window.removeEventListener('voice:add-step', handler as EventListener)
  }, [addNode, screenToFlowPosition])

  return (
    <div ref={wrapper} className="relative min-h-0 flex-1 bg-bg">
      <ReactFlow<StepNode>
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        onNodeClick={(_e, n: Node) => setSelected(n.id)}
        onPaneClick={() => setSelected(null)}
        onDrop={onDrop}
        onDragOver={onDragOver}
        deleteKeyCode={['Delete', 'Backspace']}
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
      {connectionError && (
        <div
          data-testid="connection-error"
          role="alert"
          className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-[8px] border border-red-500/40 bg-red-500/10 px-3 py-1.5 text-xs text-red-300"
        >
          {connectionError}
        </div>
      )}
      <BranchLabelDialog />
    </div>
  )
}
