export type ChecklistStep = {
  key: 'phone' | 'kb' | 'voice' | 'guardrails' | 'tools' | 'launch'
  label: string
  status: 'done' | 'current' | 'todo'
}

export const CHECKLIST: ChecklistStep[] = [
  { key: 'phone', label: 'Phone Number', status: 'done' },
  { key: 'kb', label: 'Knowledge Base', status: 'done' },
  { key: 'voice', label: 'Voice', status: 'done' },
  { key: 'guardrails', label: 'Guardrails', status: 'current' },
  { key: 'tools', label: 'Tools', status: 'todo' },
  { key: 'launch', label: 'Launch', status: 'todo' },
]

export type TranscriptLine = {
  id: string
  who: 'agent' | 'caller'
  text: string
  t: string
}

export const SEED_TRANSCRIPT: TranscriptLine[] = [
  { id: 't1', who: 'agent', t: '00:02', text: 'Hi! Thanks for calling Acme Support. How can I help today?' },
  { id: 't2', who: 'caller', t: '00:08', text: 'Hey, I got billed twice for last month.' },
  { id: 't3', who: 'agent', t: '00:11', text: "I'm sorry about that. Let me pull up your account — can I get the last four digits of your phone?" },
  { id: 't4', who: 'caller', t: '00:17', text: '5318.' },
  { id: 't5', who: 'agent', t: '00:20', text: 'Got it — Sarah, right? I see two charges for $42 on April 12.' },
  { id: 't6', who: 'caller', t: '00:28', text: 'Yeah exactly. Can you refund one?' },
]

export const STREAM_TRANSCRIPT: TranscriptLine[] = [
  { id: 'ts1', who: 'agent', t: '00:31', text: "Refunding one charge now — you'll see it in 3–5 business days." },
  { id: 'ts2', who: 'caller', t: '00:36', text: 'Perfect, thanks.' },
  { id: 'ts3', who: 'agent', t: '00:38', text: 'Anything else I can help with?' },
  { id: 'ts4', who: 'caller', t: '00:41', text: "No, that's it." },
  { id: 'ts5', who: 'agent', t: '00:43', text: 'Have a great day!' },
]

export type ToolCall = {
  id: string
  name: string
  status: 'pending' | 'success' | 'failed'
  ms: number
}

export const TOOL_CALLS: ToolCall[] = [
  { id: 'tc1', name: 'lookup_account', status: 'success', ms: 142 },
  { id: 'tc2', name: 'fetch_charges', status: 'success', ms: 318 },
  { id: 'tc3', name: 'refund_charge', status: 'pending', ms: 0 },
  { id: 'tc4', name: 'create_ticket', status: 'pending', ms: 0 },
  { id: 'tc5', name: 'send_email', status: 'failed', ms: 5012 },
]

export const SCORE_BREAKDOWN = [
  { key: 'knowledge', label: 'Knowledge', value: 96 },
  { key: 'latency', label: 'Latency', value: 88 },
  { key: 'empathy', label: 'Empathy', value: 94 },
  { key: 'compliance', label: 'Compliance', value: 90 },
] as const

export const COMPLIANCE = [
  { key: 'pii', label: 'PII Redaction', status: 'ok' as const },
  { key: 'rec', label: 'Call Recording', status: 'ok' as const },
  { key: 'consent', label: '2-party consent', status: 'warn' as const },
  { key: 'hipaa', label: 'HIPAA mode', status: 'off' as const },
]

export const LAUNCH_HISTORY = [
  { id: 'l1', date: 'May 10, 2026', env: 'Production', version: 'v12', status: 'live' as const },
  { id: 'l2', date: 'May 09, 2026', env: 'Staging', version: 'v11', status: 'archived' as const },
  { id: 'l3', date: 'May 07, 2026', env: 'Staging', version: 'v10', status: 'archived' as const },
  { id: 'l4', date: 'May 05, 2026', env: 'Production', version: 'v9', status: 'rolled-back' as const },
]
