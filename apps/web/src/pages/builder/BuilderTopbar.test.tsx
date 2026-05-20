import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api', () => ({
  api: { publishAgent: vi.fn() },
  getApiBase: () => 'http://test',
}))

import { api } from '@/lib/api'
import { BuilderTopbar } from './BuilderTopbar'
import { useBuilder, type AgentMeta } from './store'

const META: AgentMeta = {
  id: 'ag_1',
  name: 'Acme Agent',
  versionId: 'agv_1',
  versionNumber: 3,
  firstMessage: 'hi',
  systemPrompt: 'be brief',
  modelId: 'gemini/gemini-3.1-flash-lite',
  voiceId: '21m00Tcm4TlvDq8ikWAM',
  publishedVersionId: 'agv_1', // production
  analysisPlan: null,
  dynamicVariables: { foo: 'bar' },
}

function withRouter(ui: React.ReactNode) {
  return <MemoryRouter>{ui}</MemoryRouter>
}

beforeEach(() => {
  useBuilder.setState({
    agentMeta: META,
    saveStatus: 'idle',
    saveError: null,
    testCallAgentId: null,
  })
  vi.clearAllMocks()
})

afterEach(cleanup)

describe('BuilderTopbar', () => {
  it('renders agent name + version + production env chip', () => {
    render(withRouter(<BuilderTopbar agentId="ag_1" />))
    expect(screen.getByTestId('builder-agent-name')).toHaveTextContent('Acme Agent')
    expect(screen.getByTestId('version-picker')).toHaveTextContent('Version 3')
    expect(screen.getByTestId('builder-env-chip')).toHaveTextContent('Production')
  })

  it('shows Draft env when versionId differs from publishedVersionId', () => {
    useBuilder.setState({
      agentMeta: { ...META, publishedVersionId: 'agv_old' },
    })
    render(withRouter(<BuilderTopbar agentId="ag_1" />))
    expect(screen.getByTestId('builder-env-chip')).toHaveTextContent('Draft')
  })

  it('falls back to demo name when meta is null + id is demo', () => {
    useBuilder.setState({ agentMeta: null })
    render(withRouter(<BuilderTopbar agentId="demo" />))
    expect(screen.getByTestId('builder-agent-name')).toHaveTextContent(
      'Sales Qualifier Agent',
    )
    // test-call button disabled when meta is null
    expect(screen.getByTestId('test-call')).toBeDisabled()
    expect(screen.getByTestId('publish')).toBeDisabled()
  })

  it('flips testCallAgentId in the store on Test Call click', () => {
    render(withRouter(<BuilderTopbar agentId="ag_1" />))
    expect(useBuilder.getState().testCallAgentId).toBeNull()
    fireEvent.click(screen.getByTestId('test-call'))
    expect(useBuilder.getState().testCallAgentId).toBe('ag_1')
  })

  it('publishes happy-path, rotates versionId, marks saved', async () => {
    ;(api.publishAgent as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'ag_1',
      published_version_id: 'agv_1',
      versions: [
        { id: 'agv_1', version: 3 },
        { id: 'agv_2', version: 4 },
      ],
    })
    render(withRouter(<BuilderTopbar agentId="ag_1" />))
    fireEvent.click(screen.getByTestId('publish'))
    await waitFor(() =>
      expect(api.publishAgent).toHaveBeenCalledWith('ag_1', {
        version_id: 'agv_1',
        env: 'production',
      }),
    )
    await waitFor(() => {
      const meta = useBuilder.getState().agentMeta!
      expect(meta.versionId).toBe('agv_2')
      expect(meta.versionNumber).toBe(4)
    })
    expect(useBuilder.getState().saveStatus).toBe('saved')
  })

  it('publish failure surfaces parsed errors banner', async () => {
    const err = new Error(
      'Error: 422 Unprocessable Entity — ' +
        '{"detail":{"field":"analysis_plan","errors":["bad summary","bad schema"]}}',
    )
    ;(api.publishAgent as ReturnType<typeof vi.fn>).mockRejectedValue(err)
    render(withRouter(<BuilderTopbar agentId="ag_1" />))
    fireEvent.click(screen.getByTestId('publish'))
    const banner = await screen.findByTestId('publish-errors')
    expect(banner).toHaveTextContent('bad summary')
    expect(banner).toHaveTextContent('bad schema')
  })
})
