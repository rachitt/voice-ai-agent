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

async function sessionReq<T>(path: string, init: RequestInit = {}): Promise<T | null> {
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (res.status === 204) return null
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
  mintStreamToken: (callId: string) =>
    req<StreamToken>(`/v1/calls/${encodeURIComponent(callId)}/stream-token`, {
      method: 'POST',
    }),
  consoleSummary: () => req<ConsoleSummary>(`/v1/console/summary`),
}

// --- api keys (dashboard / session auth) -----------------------------------

export interface ApiKeyRow {
  id: string
  name: string
  prefix: string
  last_used_at: string | null
  revoked_at: string | null
  created_at: string
}

export interface ApiKeyCreated extends ApiKeyRow {
  key: string
}

// --- calls -----------------------------------------------------------------

export interface CallListItem {
  id: string
  agent_id: string
  direction: 'inbound' | 'outbound' | 'web' | string
  status: string
  from_number: string | null
  to_number: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  has_recording: boolean
  created_at: string
}

export interface CallListPage {
  items: CallListItem[]
  next_cursor: string | null
  total: number | null
}

export interface CallDetail extends CallListItem {
  transcript: { role?: string; who?: string; text?: string }[] | null
  provider_call_id: string | null
  phone_number_id: string | null
  analysis: Record<string, unknown> | null
  dynamic_variables: Record<string, unknown>
  recording_s3_key: string | null
}

export const calls = {
  list: (opts: { limit?: number; cursor?: string; agent_id?: string; has_recording?: boolean } = {}) => {
    const qs = new URLSearchParams()
    if (opts.limit) qs.set('limit', String(opts.limit))
    if (opts.cursor) qs.set('cursor', opts.cursor)
    if (opts.agent_id) qs.set('agent_id', opts.agent_id)
    if (opts.has_recording !== undefined) qs.set('has_recording', String(opts.has_recording))
    const tail = qs.toString() ? `?${qs.toString()}` : ''
    return req<CallListPage>(`/v1/calls${tail}`)
  },
  get: (id: string) => req<CallDetail>(`/v1/calls/${encodeURIComponent(id)}`),
  // Audio elements can't carry an Authorization header. Fetch the WAV as a
  // blob (with Bearer auth) and let the caller turn it into an object URL.
  recordingBlob: async (id: string): Promise<Blob> => {
    const r = await fetch(
      `${getApiBase()}/v1/calls/${encodeURIComponent(id)}/recording`,
      { headers: { authorization: `Bearer ${getApiKey()}` } },
    )
    if (!r.ok) {
      const body = await r.text().catch(() => '')
      throw new Error(`${r.status} ${r.statusText} ${body}`)
    }
    return await r.blob()
  },
}

export const apiKeys = {
  list: () => sessionReq<ApiKeyRow[]>(`/v1/api-keys`),
  create: (name: string) =>
    sessionReq<ApiKeyCreated>(`/v1/api-keys`, {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  revoke: (id: string) =>
    sessionReq<null>(`/v1/api-keys/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

// --- console summary -------------------------------------------------------

export interface ConsoleChecklistStep {
  key: string
  label: string
  status: 'done' | 'current' | 'todo'
}
export interface ConsoleSummary {
  checklist: ConsoleChecklistStep[]
  today: {
    calls: number
    completed: number
    failed: number
    avg_duration_ms: number
    calls_delta_vs_yesterday: number
  }
  recent_tool_calls: {
    id: string
    name: string
    status: 'success' | 'failed' | 'pending'
    call_id: string
    at: string
  }[]
  launch_history: {
    id: string
    version: string
    env: string
    date: string
    agent_id: string
    agent_name: string
    status: 'live' | 'archived' | 'rolled-back'
  }[]
  score_breakdown: { key: string; label: string; value: number }[]
  compliance: { key: string; label: string; status: 'ok' | 'warn' | 'off' }[]
}

export interface StreamToken {
  token: string
  expires_at: number
  ttl_seconds: number
}

// --- auth ------------------------------------------------------------------

export interface MeResponse {
  user: { id: string; email: string; name: string | null; avatar_url: string | null }
  org: { id: string; name: string; slug: string } | null
}

export const auth = {
  loginGoogleUrl: () => `${getApiBase()}/v1/auth/login/google`,
  me: async (): Promise<MeResponse | null> => {
    const r = await fetch(`${getApiBase()}/v1/auth/me`, { credentials: 'include' })
    if (r.status === 401) return null
    if (!r.ok) throw new Error(`/me ${r.status}`)
    return (await r.json()) as MeResponse
  },
  logout: async (): Promise<void> => {
    await fetch(`${getApiBase()}/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    })
  },
}

/** Pick the latest AgentVersion (highest `version`) — that's the active draft. */
export function latestVersion(detail: AgentDetail): AgentVersion | null {
  if (!detail.versions || detail.versions.length === 0) return null
  return [...detail.versions].sort((a, b) => b.version - a.version)[0]
}
