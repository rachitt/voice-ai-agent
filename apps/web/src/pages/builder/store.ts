import { create } from 'zustand'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import type { AgentDetail, AgentVersion } from '@/lib/api'
import { canConnect } from './connection-rules'
import type { StepData, StepEdge, StepKind, StepNode } from './types'

export interface AgentMeta {
  id: string
  name: string
  versionId: string
  versionNumber: number
  firstMessage: string | null
  systemPrompt: string | null
  modelId: string
  voiceId: string
  publishedVersionId: string | null
  analysisPlan: Record<string, unknown> | null
  dynamicVariables: Record<string, unknown>
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

type State = {
  nodes: StepNode[]
  edges: StepEdge[]
  selectedId: string | null
  /** Last connection rejection reason (toast). */
  connectionError: string | null
  /** When a label-required connection is in flight, the dialog reads this. */
  pendingBranchConnect: Connection | null
  /** Server-backed agent identity. Null until hydrated (or in offline demo). */
  agentMeta: AgentMeta | null
  saveStatus: SaveStatus
  saveError: string | null
  /** ID of the flow node currently being executed during a live test call.
   *  Null when there's no active call. Pure UI state — driven by `flow_node`
   *  events on the test-call WS, consumed by StepNode to glow + scroll into
   *  view. Never persisted. */
  activeFlowNodeId: string | null
  /** Optional progress hint emitted alongside `flow_node` (currently only
   *  by slot_fill: {filled: string[], missing: string[]}). */
  activeFlowProgress: { filled: string[]; missing: string[] } | null
  setActiveFlowNodeId: (
    id: string | null,
    progress?: { filled: string[]; missing: string[] } | null,
  ) => void
  /** Set when the user presses Test Call. Drives the right-panel tab row so
   *  the inspector reveals a 'Test Call' tab alongside 'Node'. Cleared on
   *  hangup so the inspector goes back to its plain single-pane shape. */
  testCallAgentId: string | null
  openTestCall: (agentId: string) => void
  closeTestCall: () => void
  setSelected: (id: string | null) => void
  setConnectionError: (msg: string | null) => void
  setPendingBranchConnect: (c: Connection | null) => void
  commitBranchConnect: (label: string) => void
  onNodesChange: (changes: NodeChange<StepNode>[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (c: Connection) => void
  addNode: (kind: StepKind, position: { x: number; y: number }) => string
  updateNodeData: (id: string, patch: Partial<StepData>) => void
  removeNode: (id: string) => void
  removeSelected: () => void
  duplicateNode: (id: string) => void
  clearGraph: () => void
  hydrateFromAgent: (detail: AgentDetail, ver: AgentVersion) => void
  setSaveStatus: (s: SaveStatus, err?: string | null) => void
  setAgentName: (name: string) => void
  setAgentMetaFields: (patch: Partial<AgentMeta>) => void
}

const seed = (): { nodes: StepNode[]; edges: StepEdge[] } => {
  const nodes: StepNode[] = [
    n('greet', 'greeting', 'Greeting', 'Hi! Thanks for calling…', 400, 40),
    n('collect-name', 'collect', 'Collect Info', "What's your name?", 400, 200),
    n('cond', 'condition', 'Condition', 'has_account == true', 400, 360),
    n('collect-acct', 'collect', 'Collect Info', 'Account number?', 220, 520),
    n('vm', 'voicemail', 'Voicemail', 'Please leave a message', 600, 520),
    n('api', 'api', 'API Call', 'POST /tickets', 220, 680),
    n('end', 'end', 'End Call', 'Wrap up', 600, 680),
  ]
  const edges: StepEdge[] = [
    e('greet', 'collect-name'),
    e('collect-name', 'cond'),
    e('cond', 'collect-acct', 'yes'),
    e('cond', 'vm', 'no'),
    e('collect-acct', 'api'),
    e('vm', 'end'),
  ]
  return { nodes, edges }
}

function n(id: string, kind: StepKind, title: string, subtitle: string, x: number, y: number): StepNode {
  return {
    id,
    type: 'step',
    position: { x, y },
    data: {
      kind,
      title,
      subtitle,
      voice: 'Aria Power',
      mode: 'Normal',
      prompt: subtitle,
      interruption: 'allow',
      retry: 'exponential',
      webhook: kind === 'api' ? 'https://hooks.acme.com/ticket' : '',
      sample: 'acme_company',
    },
  }
}

function e(source: string, target: string, label?: string): StepEdge {
  return {
    id: `${source}->${target}`,
    source,
    target,
    type: 'smoothstep',
    animated: false,
    label,
  }
}

let counter = 0
const nextId = (kind: string) => `${kind}-${Date.now().toString(36)}-${counter++}`

const TITLES: Record<StepKind, string> = {
  greeting: 'Greeting',
  collect: 'Collect Info',
  slot_fill: 'Slot Fill',
  tool_call: 'Tool Call',
  api: 'API Call',
  condition: 'Condition',
  transfer: 'Transfer',
  voicemail: 'Voicemail',
  kb_lookup: 'Knowledge Base',
  end: 'End Call',
}

export const useBuilder = create<State>((set, get) => ({
  ...seed(),
  selectedId: 'collect-name',
  connectionError: null,
  pendingBranchConnect: null,
  agentMeta: null,
  saveStatus: 'idle',
  saveError: null,
  activeFlowNodeId: null,
  activeFlowProgress: null,
  setActiveFlowNodeId: (id, progress) =>
    set({ activeFlowNodeId: id, activeFlowProgress: progress ?? null }),
  testCallAgentId: null,
  openTestCall: (agentId) => set({ testCallAgentId: agentId }),
  closeTestCall: () =>
    set({ testCallAgentId: null, activeFlowNodeId: null, activeFlowProgress: null }),
  setSelected: (id) => set({ selectedId: id }),
  setConnectionError: (msg) => set({ connectionError: msg }),
  setPendingBranchConnect: (c) => set({ pendingBranchConnect: c }),
  commitBranchConnect: (label) => {
    const c = get().pendingBranchConnect
    if (!c || !c.source || !c.target) {
      set({ pendingBranchConnect: null })
      return
    }
    const check = canConnect(c.source, c.target, get().nodes, get().edges)
    if (!check.ok) {
      set({ pendingBranchConnect: null, connectionError: check.reason ?? 'invalid connection' })
      return
    }
    set({
      edges: addEdge({ ...c, type: 'smoothstep', label }, get().edges),
      pendingBranchConnect: null,
      connectionError: null,
    })
  },
  onNodesChange: (changes) => {
    const removed = new Set(
      changes.filter((c) => c.type === 'remove').map((c) => (c as { id: string }).id),
    )
    const nextNodes = applyNodeChanges(changes, get().nodes)
    set({
      nodes: nextNodes,
      // also drop any edges that point at removed nodes
      edges: removed.size
        ? get().edges.filter((e) => !removed.has(e.source) && !removed.has(e.target))
        : get().edges,
      selectedId: removed.has(get().selectedId ?? '') ? null : get().selectedId,
    })
  },
  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),
  onConnect: (c) => {
    const check = canConnect(c.source, c.target, get().nodes, get().edges)
    if (!check.ok) {
      set({ connectionError: check.reason ?? 'invalid connection' })
      return
    }
    if (check.needsLabel) {
      set({ pendingBranchConnect: c, connectionError: null })
      return
    }
    set({
      edges: addEdge({ ...c, type: 'smoothstep' }, get().edges),
      connectionError: null,
    })
  },
  addNode: (kind, position) => {
    const id = nextId(kind)
    const node: StepNode = {
      id,
      type: 'step',
      position,
      data: {
        kind,
        title: TITLES[kind],
        subtitle: 'Configure…',
        voice: 'Aria Power',
        mode: 'Normal',
        prompt: '',
        interruption: 'allow',
        retry: 'exponential',
      },
    }
    set({ nodes: [...get().nodes, node], selectedId: id })
    return id
  },
  updateNodeData: (id, patch) =>
    set({
      nodes: get().nodes.map((nd) =>
        nd.id === id ? { ...nd, data: { ...nd.data, ...patch } } : nd,
      ),
    }),
  removeNode: (id) =>
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selectedId: get().selectedId === id ? null : get().selectedId,
    }),
  removeSelected: () => {
    const id = get().selectedId
    if (!id) return
    set({
      nodes: get().nodes.filter((n) => n.id !== id),
      edges: get().edges.filter((e) => e.source !== id && e.target !== id),
      selectedId: null,
    })
  },
  duplicateNode: (id) => {
    const src = get().nodes.find((n) => n.id === id)
    if (!src) return
    const newId = nextId(src.data.kind)
    const node: StepNode = {
      ...src,
      id: newId,
      position: { x: src.position.x + 40, y: src.position.y + 40 },
      data: { ...src.data, title: `${src.data.title} copy` },
      selected: false,
    }
    set({ nodes: [...get().nodes, node], selectedId: newId })
  },
  clearGraph: () => set({ nodes: [], edges: [], selectedId: null }),
  hydrateFromAgent: (detail, ver) => {
    const fg = ver.flow_graph as { nodes?: unknown[]; edges?: unknown[] } | null
    const nextNodes = (fg?.nodes as StepNode[] | undefined) ?? []
    const nextEdges = (fg?.edges as StepEdge[] | undefined) ?? []
    set({
      nodes: nextNodes,
      edges: nextEdges,
      selectedId: null,
      agentMeta: {
        id: detail.id,
        name: detail.name,
        versionId: ver.id,
        versionNumber: ver.version,
        firstMessage: ver.first_message,
        systemPrompt: ver.system_prompt,
        modelId: ver.model_id,
        voiceId: ver.voice_id,
        publishedVersionId: detail.published_version_id,
        analysisPlan: ver.analysis_plan ?? null,
        dynamicVariables: ver.dynamic_variables ?? {},
      },
      saveStatus: 'idle',
      saveError: null,
    })
  },
  setSaveStatus: (s, err = null) => set({ saveStatus: s, saveError: err }),
  setAgentName: (name) => {
    const m = get().agentMeta
    if (m) set({ agentMeta: { ...m, name } })
  },
  setAgentMetaFields: (patch) => {
    const m = get().agentMeta
    if (m) set({ agentMeta: { ...m, ...patch } })
  },
}))
