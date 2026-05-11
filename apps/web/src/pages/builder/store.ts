import { create } from 'zustand'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from '@xyflow/react'
import type { StepData, StepEdge, StepKind, StepNode } from './types'

type State = {
  nodes: StepNode[]
  edges: StepEdge[]
  selectedId: string | null
  setSelected: (id: string | null) => void
  onNodesChange: (changes: NodeChange<StepNode>[]) => void
  onEdgesChange: (changes: EdgeChange[]) => void
  onConnect: (c: Connection) => void
  addNode: (kind: StepKind, position: { x: number; y: number }) => void
  updateNodeData: (id: string, patch: Partial<StepData>) => void
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

export const useBuilder = create<State>((set, get) => ({
  ...seed(),
  selectedId: 'collect-name',
  setSelected: (id) => set({ selectedId: id }),
  onNodesChange: (changes) =>
    set({ nodes: applyNodeChanges(changes, get().nodes) }),
  onEdgesChange: (changes) =>
    set({ edges: applyEdgeChanges(changes, get().edges) }),
  onConnect: (c) =>
    set({ edges: addEdge({ ...c, type: 'smoothstep' }, get().edges) }),
  addNode: (kind, position) => {
    const id = nextId(kind)
    const titles: Record<StepKind, string> = {
      greeting: 'Greeting',
      collect: 'Collect Info',
      api: 'API Call',
      condition: 'Condition',
      transfer: 'Transfer',
      voicemail: 'Voicemail',
      end: 'End Call',
    }
    const node: StepNode = {
      id,
      type: 'step',
      position,
      data: {
        kind,
        title: titles[kind],
        subtitle: 'Configure…',
        voice: 'Aria Power',
        mode: 'Normal',
        prompt: '',
        interruption: 'allow',
        retry: 'exponential',
      },
    }
    set({ nodes: [...get().nodes, node], selectedId: id })
  },
  updateNodeData: (id, patch) =>
    set({
      nodes: get().nodes.map((nd) =>
        nd.id === id ? { ...nd, data: { ...nd.data, ...patch } } : nd,
      ),
    }),
}))
