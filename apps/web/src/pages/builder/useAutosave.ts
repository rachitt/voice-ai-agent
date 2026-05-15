import { useEffect, useRef } from 'react'
import { api } from '@/lib/api'
import { useBuilder } from './store'

const DEBOUNCE_MS = 1500

/**
 * Debounced PATCH /v1/agents/:id whenever the graph or agent metadata
 * changes. No-op for offline demo route. Backend mutates the live draft
 * AgentVersion in place; a new version is only minted on Publish.
 */
export function useAutosave(agentId: string) {
  const nodes = useBuilder((s) => s.nodes)
  const edges = useBuilder((s) => s.edges)
  const agentMeta = useBuilder((s) => s.agentMeta)
  const setSaveStatus = useBuilder((s) => s.setSaveStatus)
  const setAgentMetaFields = useBuilder((s) => s.setAgentMetaFields)

  const firstRun = useRef(true)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inflight = useRef<AbortController | null>(null)

  useEffect(() => {
    if (agentId === 'demo') return
    if (!agentMeta) return
    // Skip immediately after hydrate (first tick after meta arrives).
    if (firstRun.current) {
      firstRun.current = false
      return
    }

    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      inflight.current?.abort()
      inflight.current = new AbortController()
      setSaveStatus('saving')
      try {
        const next = await api.patchAgent(agentMeta.id, {
          name: agentMeta.name,
          first_message: agentMeta.firstMessage,
          system_prompt: agentMeta.systemPrompt,
          model_id: agentMeta.modelId,
          voice_id: agentMeta.voiceId,
          flow_graph: { nodes, edges },
          analysis_plan: agentMeta.analysisPlan,
          dynamic_variables: agentMeta.dynamicVariables,
        })
        setAgentMetaFields({ versionId: next.id, versionNumber: next.version })
        setSaveStatus('saved')
      } catch (e) {
        setSaveStatus('error', String(e))
      }
    }, DEBOUNCE_MS)

    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
    // agentMeta identity changes when metadata edits land; nodes/edges trigger graph saves.
  }, [agentId, agentMeta, nodes, edges, setSaveStatus, setAgentMetaFields])
}
