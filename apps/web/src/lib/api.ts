// Minimal typed API client. Reads API key + base URL from localStorage.

export const API_BASE_KEY = 'voice2.api_base'
export const API_KEY_KEY = 'voice2.api_key'

export function getApiBase(): string {
  return localStorage.getItem(API_BASE_KEY) || 'http://localhost:8000'
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_KEY) || ''
}

export function setApiBase(v: string): void {
  localStorage.setItem(API_BASE_KEY, v)
}

export function setApiKey(v: string): void {
  localStorage.setItem(API_KEY_KEY, v)
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${getApiKey()}`,
      ...(init.headers || {}),
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText} ${body}`)
  }
  return (await res.json()) as T
}

// --- types -----------------------------------------------------------------

export interface AgentSummary {
  id: string
  name: string
  published_version_id: string | null
  created_at: string
}

export interface FlowGraph {
  nodes: unknown[]
  edges: unknown[]
}

export interface AgentVersion {
  id: string
  version: number
  env: string
  first_message: string | null
  system_prompt: string | null
  model_id: string
  voice_id: string
  stt_id: string
  language: string
  interruption_sensitivity: number
  vad_silence_ms: number
  flow_graph: FlowGraph | null
  tools: string[]
  knowledge_base_ids: string[]
  analysis_plan: Record<string, unknown> | null
  server_url: string | null
  created_at: string
}

export interface AgentDetail extends AgentSummary {
  versions: AgentVersion[]
}

export interface AgentUpdateBody {
  name?: string
  first_message?: string | null
  system_prompt?: string | null
  model_id?: string
  voice_id?: string
  flow_graph?: FlowGraph | null
  tools?: string[]
}

export interface AgentCreateBody extends AgentUpdateBody {
  name: string
}

export interface PublishBody {
  version_id: string
  env?: 'draft' | 'staging' | 'production'
}

export interface ValidatorErrorDetail {
  errors: string[]
  warnings?: string[]
}

export interface WebCallCreated {
  id: string
  agent_id: string
  direction: string
  status: string
  ws_token: string
  ws_url: string
}

// --- endpoints -------------------------------------------------------------

export const api = {
  listAgents: () => req<AgentSummary[]>(`/v1/agents`),
  getAgent: (id: string) => req<AgentDetail>(`/v1/agents/${id}`),
  createAgent: (body: AgentCreateBody) =>
    req<AgentDetail>(`/v1/agents`, { method: 'POST', body: JSON.stringify(body) }),
  patchAgent: (id: string, body: AgentUpdateBody) =>
    req<AgentVersion>(`/v1/agents/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  publishAgent: (id: string, body: PublishBody) =>
    req<AgentDetail>(`/v1/agents/${id}/publish`, {
      method: 'POST',
      body: JSON.stringify({ env: 'production', ...body }),
    }),
  createWebCall: (agentId: string) =>
    req<WebCallCreated>(`/v1/calls/web`, {
      method: 'POST',
      body: JSON.stringify({ agent_id: agentId }),
    }),
}

/** Pick the latest AgentVersion (highest `version`) — that's the active draft. */
export function latestVersion(detail: AgentDetail): AgentVersion | null {
  if (!detail.versions || detail.versions.length === 0) return null
  return [...detail.versions].sort((a, b) => b.version - a.version)[0]
}
