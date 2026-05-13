// Typed API client.
//
// Auth model:
//   - Dashboard users authenticate via httpOnly session cookie (set on
//     /login → exchanged for an API key, OR via Google OAuth callback).
//   - Cookies are sent automatically because every fetch sets
//     `credentials: 'include'`.
//   - The API key NEVER lives in localStorage anymore — it is exchanged once
//     for a session cookie and discarded. This eliminates the XSS-extracts-
//     credential risk that the old `localStorage.getItem('voice2.api_key')`
//     approach carried.
//
// Only ergonomic state still lives in localStorage:
//   - voice2.api_base (lets dev point the UI at staging/prod)
//
// `req()` throws `ApiError` (with .status) so callers can branch on 401.

export const API_BASE_KEY = 'voice2.api_base'

export function getApiBase(): string {
  // Default to same-origin so the dev vite proxy (and prod's identical-origin
  // deploy) carry the session cookie. Cross-origin overrides remain possible
  // for inspect/multi-env work — drop them in localStorage by hand.
  return localStorage.getItem(API_BASE_KEY) || ''
}

export function setApiBase(v: string): void {
  localStorage.setItem(API_BASE_KEY, v)
}

export class ApiError extends Error {
  status: number
  body: string
  constructor(status: number, statusText: string, body: string) {
    super(`${status} ${statusText} ${body}`.trim())
    this.status = status
    this.body = body
  }
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

// Double-submit CSRF: read the non-httpOnly voice_csrf cookie set on
// session mint and echo it back as a header on writes. The middleware
// rejects writes when header ≠ cookie, so a same-site attacker can't
// forge a POST against a victim's session without also being able to
// set the header (which cross-site code cannot).
function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)voice_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {})
  if (init.body && !headers.has('content-type')) {
    headers.set('content-type', 'application/json')
  }
  const method = (init.method || 'GET').toUpperCase()
  if (!SAFE_METHODS.has(method) && !headers.has('x-csrf-token')) {
    const tok = readCsrfCookie()
    if (tok) headers.set('x-csrf-token', tok)
  }
  const res = await fetch(`${getApiBase()}${path}`, {
    ...init,
    credentials: 'include',
    headers,
  })
  if (res.status === 204) return null as T
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, res.statusText, body)
  }
  return (await res.json()) as T
}

// Back-compat alias — historically /v1/api-keys/* was the only set of routes
// using cookie auth. Now `req()` does the same thing for every endpoint.
const sessionReq = req

// `auth` lives further down — declared alongside MeResponse so consumers
// keep importing both from the same place.

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
  dynamic_variables: Record<string, unknown>
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
  analysis_plan?: Record<string, unknown> | null
  dynamic_variables?: Record<string, unknown>
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
  createWebCall: (agentId: string, dynamicVariables?: Record<string, unknown>) =>
    req<WebCallCreated>(`/v1/calls/web`, {
      method: 'POST',
      body: JSON.stringify({
        agent_id: agentId,
        ...(dynamicVariables && Object.keys(dynamicVariables).length
          ? { dynamic_variables: dynamicVariables }
          : {}),
      }),
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
  recordingUrl: (id: string) =>
    req<{ url: string | null; expires_in: number }>(
      `/v1/calls/${encodeURIComponent(id)}/recording-url`,
    ),
  // Audio elements can't carry headers, so when the object store isn't
  // configured (no presigned URL) we fetch the WAV as a blob using the
  // session cookie and hand back an object URL.
  recordingBlob: async (id: string): Promise<Blob> => {
    const r = await fetch(
      `${getApiBase()}/v1/calls/${encodeURIComponent(id)}/recording`,
      { credentials: 'include' },
    )
    if (!r.ok) {
      const body = await r.text().catch(() => '')
      throw new ApiError(r.status, r.statusText, body)
    }
    return await r.blob()
  },
}

// --- phone numbers ---------------------------------------------------------

export interface PhoneNumber {
  id: string
  e164: string
  provider: string
  provider_resource_id: string | null
  agent_id: string | null
  status: string
  created_at: string
}

export interface PhoneNumberCreate {
  e164: string
  provider?: string
  provider_resource_id?: string | null
  agent_id?: string | null
}

export interface PhoneNumberUpdate {
  agent_id?: string | null
  status?: string | null
}

export const phoneNumbers = {
  list: () => req<PhoneNumber[]>(`/v1/phone-numbers`),
  create: (body: PhoneNumberCreate) =>
    req<PhoneNumber>(`/v1/phone-numbers`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (id: string, body: PhoneNumberUpdate) =>
    req<PhoneNumber>(`/v1/phone-numbers/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
}

// --- tools -----------------------------------------------------------------

export interface ToolRow {
  id: string
  name: string
  description: string | null
  server_url: string
  method: string
  headers: Record<string, string>
  params_schema: Record<string, unknown>
  timeout_ms: number
  created_at: string
  updated_at: string
}

export interface ToolCreate {
  name: string
  description?: string | null
  server_url: string
  method?: string
  headers?: Record<string, string>
  params_schema?: Record<string, unknown>
  timeout_ms?: number
}

export type ToolUpdate = Partial<ToolCreate>

export const tools = {
  list: () => req<ToolRow[]>(`/v1/tools`),
  create: (body: ToolCreate) =>
    req<ToolRow>(`/v1/tools`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  update: (id: string, body: ToolUpdate) =>
    req<ToolRow>(`/v1/tools/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  remove: (id: string) =>
    fetch(`${getApiBase()}/v1/tools/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      credentials: 'include',
    }).then((r) => {
      if (!r.ok && r.status !== 204) throw new ApiError(r.status, r.statusText, '')
    }),
}

// --- knowledge bases -------------------------------------------------------

export interface KnowledgeBase {
  id: string
  name: string
  embedding_model: string
  created_at: string
}

export interface KbSource {
  id: string
  kb_id: string
  name: string
  kind: string
  status: 'queued' | 'ingesting' | 'ready' | 'error' | string
  error: string | null
  created_at: string
}

export interface KbQueryHit {
  chunk_id: string
  source_id: string
  source_name: string | null
  text: string
  score: number
}

export interface KbQueryResult {
  hits: KbQueryHit[]
  elapsed_ms: number
}

export const knowledgeBases = {
  list: () => req<KnowledgeBase[]>(`/v1/knowledge-bases`),
  create: (body: { name: string; embedding_model?: string }) =>
    req<KnowledgeBase>(`/v1/knowledge-bases`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  query: (kbId: string, body: { query: string; top_k?: number }) =>
    req<KbQueryResult>(`/v1/knowledge-bases/${encodeURIComponent(kbId)}/query`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listSources: (kbId: string) =>
    req<KbSource[]>(`/v1/knowledge-bases/${encodeURIComponent(kbId)}/sources`),
  addSource: (kbId: string, body: { name: string; kind: string; s3_key?: string | null }) =>
    req<KbSource>(`/v1/knowledge-bases/${encodeURIComponent(kbId)}/sources`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  uploadSource: async (kbId: string, file: File): Promise<KbSource> => {
    const form = new FormData()
    form.append('file', file)
    const r = await fetch(
      `${getApiBase()}/v1/knowledge-bases/${encodeURIComponent(kbId)}/sources/upload`,
      { method: 'POST', credentials: 'include', body: form },
    )
    if (!r.ok) {
      const body = await r.text().catch(() => '')
      throw new ApiError(r.status, r.statusText, body)
    }
    return (await r.json()) as KbSource
  },
}

// --- analytics -------------------------------------------------------------

export interface AnalyticsDay {
  date: string
  count: number
  completed: number
  failed: number
}
export interface AnalyticsAgent {
  agent_id: string
  name: string
  count: number
  success_rate: number
}
export interface AnalyticsResponse {
  range: '7d' | '30d' | '90d' | string
  volume_by_day: AnalyticsDay[]
  by_agent: AnalyticsAgent[]
  total_calls: number
  avg_duration_ms: number
  p50_duration_ms: number
  p95_duration_ms: number
  success_rate: number
}

export const analytics = {
  get: (range: '7d' | '30d' | '90d' = '7d') =>
    req<AnalyticsResponse>(`/v1/console/analytics?range=${range}`),
}

// --- model + voice catalog -------------------------------------------------

export interface CatalogModel {
  id: string
  label: string
  vendor: string
  tier: string
}
export interface CatalogVoice {
  id: string
  label: string
  vendor: string
  latency: string
}

export const catalog = {
  models: () => req<{ items: CatalogModel[] }>(`/v1/models`).then((r) => r.items),
  voices: () => req<{ items: CatalogVoice[] }>(`/v1/voices`).then((r) => r.items),
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
  /** Double-submit CSRF token — also set as voice_csrf cookie. */
  csrf_token?: string
}

export const auth = {
  /** Full URL to bounce the browser to Google OAuth consent. */
  loginGoogleUrl: () => `${getApiBase()}/v1/auth/login/google`,
  /** Exchange a long-lived API key for an httpOnly session cookie. */
  loginWithApiKey: (apiKey: string) =>
    req<MeResponse>(`/v1/auth/session/api-key`, {
      method: 'POST',
      body: JSON.stringify({ api_key: apiKey }),
    }),
  /** Returns the signed-in user, or null if there is no session. */
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
