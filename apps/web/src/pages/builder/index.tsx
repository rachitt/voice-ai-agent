import { useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { api, latestVersion } from '@/lib/api'
import { BuilderTopbar } from './BuilderTopbar'
import { StepPalette } from './StepPalette'
import { FlowCanvas } from './FlowCanvas'
import { NodeInspector } from './NodeInspector'
import { useAutosave } from './useAutosave'
import { useBuilder } from './store'

export function BuilderPage() {
  const { agentId = 'demo' } = useParams()
  const hydrateFromAgent = useBuilder((s) => s.hydrateFromAgent)
  const setSaveStatus = useBuilder((s) => s.setSaveStatus)

  useEffect(() => {
    if (import.meta.env.PROD) return
    ;(window as unknown as { __voiceBuilder?: typeof useBuilder }).__voiceBuilder = useBuilder
  }, [])

  useEffect(() => {
    if (agentId === 'demo') return // offline seed graph
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
