import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, latestVersion } from '@/lib/api'
import { BuilderTopbar } from './BuilderTopbar'
import { StepPalette } from './StepPalette'
import { FlowCanvas } from './FlowCanvas'
import { NodeInspector } from './NodeInspector'
import { useAutosave } from './useAutosave'
import { useBuilder } from './store'

export function BuilderPage() {
  const { agentId = 'demo' } = useParams()
  const navigate = useNavigate()
  const hydrateFromAgent = useBuilder((s) => s.hydrateFromAgent)
  const setSaveStatus = useBuilder((s) => s.setSaveStatus)

  useEffect(() => {
    if (import.meta.env.PROD) return
    ;(window as unknown as { __voiceBuilder?: typeof useBuilder }).__voiceBuilder = useBuilder
  }, [])

  // /builder/demo used to be an offline-only seed graph. That meant Test Call
  // and Publish were permanently disabled on that URL (no `agentMeta`).
  // Resolve it to a real backing agent instead — reuse the first one in the
  // org, or mint a freshly-named "Demo Agent" if none exists. Then bounce
  // the URL so the rest of the builder hydrates as normal.
  useEffect(() => {
    if (agentId !== 'demo') return
    let cancelled = false
    ;(async () => {
      try {
        const list = await api.listAgents()
        if (cancelled) return
        if (list.length > 0) {
          navigate(`/builder/${list[0].id}`, { replace: true })
          return
        }
        const detail = await api.createAgent({
          name: 'Demo Agent',
          first_message: 'Hi! How can I help today?',
          system_prompt: 'You are a helpful voice agent. Reply briefly.',
        })
        if (cancelled) return
        navigate(`/builder/${detail.id}`, { replace: true })
      } catch (e) {
        if (!cancelled) setSaveStatus('error', String(e))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [agentId, navigate, setSaveStatus])

  useEffect(() => {
    if (agentId === 'demo') return // handled by the resolver above
    let cancelled = false
    setSaveStatus('saving') // visually 'loading' until hydrate completes
    api
      .getAgent(agentId)
      .then((detail) => {
        if (cancelled) return
        const ver = latestVersion(detail)
        if (!ver) {
          setSaveStatus('error', 'agent has no versions')
          return
        }
        hydrateFromAgent(detail, ver)
      })
      .catch((e) => {
        if (cancelled) return
        setSaveStatus('error', String(e))
      })
    return () => {
      cancelled = true
    }
  }, [agentId, hydrateFromAgent, setSaveStatus])

  useAutosave(agentId)

  return (
    <div
      data-testid="builder-root"
      className="flex h-screen w-screen flex-col overflow-hidden bg-bg text-fg"
    >
      <BuilderTopbar agentId={agentId} />
      <div className="flex min-h-0 flex-1">
        <StepPalette />
        <FlowCanvas />
        <NodeInspector />
      </div>
    </div>
  )
}
