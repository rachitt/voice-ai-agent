import type { Edge, Node } from '@xyflow/react'

export type StepKind =
  | 'greeting'
  | 'collect'
  | 'api'
  | 'condition'
  | 'transfer'
  | 'voicemail'
  | 'kb_lookup'
  | 'end'

export type RetryPolicy = 'none' | 'linear' | 'exponential'

export type StepData = {
  kind: StepKind
  title: string
  subtitle?: string
  voice?: string
  mode?: 'Normal' | 'Strict' | 'Creative'
  prompt?: string
  interruption?: 'allow' | 'block' | 'soft'
  webhook?: string
  retry?: RetryPolicy
  sample?: string
  branchLabel?: string
  kb_id?: string
  query_template?: string
  top_k?: number
}

export type StepNode = Node<StepData, 'step'>
export type StepEdge = Edge

export type PaletteItem = {
  kind: StepKind | 'sheets' | 'salesforce'
  group: 'core' | 'integrations'
  title: string
  subtitle: string
}
