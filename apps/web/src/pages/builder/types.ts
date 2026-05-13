import type { Edge, Node } from '@xyflow/react'

export type StepKind =
  | 'greeting'
  | 'collect'
  | 'slot_fill'
  | 'tool_call'
  | 'api'
  | 'condition'
  | 'transfer'
  | 'voicemail'
  | 'kb_lookup'
  | 'end'

export type RetryPolicy = 'none' | 'linear' | 'exponential'

export type SlotSpec = {
  name: string
  prompt?: string
  required?: boolean
  type?: 'string' | 'number' | 'email' | 'phone' | 'date' | 'iso_datetime'
  retry_prompt?: string
}

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
  /** slot_fill — required + optional slots to gather before advancing. */
  slots?: SlotSpec[]
  /** tool_call — builtin name OR `tool_xxx` DB ref. */
  tool?: string
  /** tool_call — {tool_param: slot_name}. Empty = 1:1 from var bag. */
  arg_map?: Record<string, string>
  /** tool_call — read back collected values and wait for explicit yes. */
  confirm_before_fire?: boolean
  /** tool_call — spoken before tool fires (e.g. "Let me check that…"). */
  pre_message?: string
  /** tool_call — auto-built when empty; override here for tone. */
  confirm_message?: string
  /** tool_call — spoken on success. */
  success_message?: string
  /** tool_call — spoken on error; routes via labelled `error` edge. */
  error_message?: string
  /** Subset of agent tools visible to the LLM while THIS node is active. */
  tools?: string[]
}

export type StepNode = Node<StepData, 'step'>
export type StepEdge = Edge

export type PaletteItem = {
  kind: StepKind | 'sheets' | 'salesforce'
  group: 'core' | 'integrations'
  title: string
  subtitle: string
}
