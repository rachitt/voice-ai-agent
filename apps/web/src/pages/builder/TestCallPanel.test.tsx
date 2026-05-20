import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@/lib/api', () => ({
  api: { createWebCall: vi.fn() },
  getApiBase: () => 'http://test',
}))

const connectMock = vi.fn(async () => undefined)
const hangupMock = vi.fn()
const sendUserTextMock = vi.fn()
type WebCallOpts = { onEvent: (ev: { type: string; [k: string]: unknown }) => void }
type FakeWebCallClient = {
  opts: WebCallOpts
  connect: typeof connectMock
  hangup: typeof hangupMock
  sendUserText: typeof sendUserTextMock
}
let lastClient: FakeWebCallClient | null = null
// Helper that asserts mount + returns the captured client; null-narrowing
// then propagates so per-test `client().opts.onEvent(...)` typechecks.
function client(): FakeWebCallClient {
  if (!lastClient) throw new Error('WebCallClient never instantiated')
  return lastClient
}

vi.mock('@/lib/webcall', () => {
  class WebCallClient {
    opts: WebCallOpts
    connect = connectMock
    hangup = hangupMock
    sendUserText = sendUserTextMock
    constructor(opts: WebCallOpts) {
      this.opts = opts
      lastClient = this as unknown as FakeWebCallClient
    }
  }
  return { WebCallClient }
})

import { api } from '@/lib/api'
import { TestCallPanel } from './TestCallPanel'

function withRouter(ui: React.ReactNode) {
  return <MemoryRouter>{ui}</MemoryRouter>
}

beforeEach(() => {
  vi.clearAllMocks()
  lastClient = null
  ;(api.createWebCall as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: 'call_abc',
    direction: 'web',
    ws_token: 'tok',
    ws_url: '/v1/calls/call_abc/ws?token=tok',
  })
})

afterEach(cleanup)

describe('TestCallPanel', () => {
  it('renders agent id chip + connecting status + overrides editor', async () => {
    render(
      withRouter(
        <TestCallPanel
          agentId="ag_1"
          agentVariableDefaults={{ foo: 'bar', count: 3 }}
          onClose={() => {}}
        />,
      ),
    )
    expect(screen.getByTestId('test-call-modal')).toBeInTheDocument()
    expect(screen.getByTestId('test-call-status')).toHaveAttribute(
      'data-status',
      'connecting',
    )
    // Override row appears with stringified non-string default.
    const ovr = screen.getByTestId('tc-override-count') as HTMLInputElement
    expect(ovr.value).toBe('3')
    await waitFor(() => expect(api.createWebCall).toHaveBeenCalledWith('ag_1', { foo: 'bar', count: '3' }))
  })

  it('surfaces inline error when createWebCall returns 401', async () => {
    ;(api.createWebCall as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('401 Unauthorized'),
    )
    render(withRouter(<TestCallPanel agentId="ag_1" onClose={() => {}} />))
    await waitFor(() =>
      expect(screen.getByTestId('test-call-status')).toHaveAttribute('data-status', 'error'),
    )
  })

  it('transitions to live on open event + appends agent_text to transcript', async () => {
    render(withRouter(<TestCallPanel agentId="ag_1" onClose={() => {}} />))
    await waitFor(() => expect(lastClient).not.toBeNull())
    client().opts.onEvent({ type: 'open' })
    await waitFor(() =>
      expect(screen.getByTestId('test-call-status')).toHaveAttribute('data-status', 'live'),
    )
    client().opts.onEvent({ type: 'server', data: { type: 'agent_text', text: 'hello caller' } })
    await waitFor(() =>
      expect(screen.getByTestId('test-call-transcript')).toHaveTextContent('hello caller'),
    )
  })

  it('sends user text + appends to transcript on Send click', async () => {
    render(withRouter(<TestCallPanel agentId="ag_1" onClose={() => {}} />))
    await waitFor(() => expect(lastClient).not.toBeNull())
    client().opts.onEvent({ type: 'open' })
    // Text input is behind the "Type instead" disclosure now (voice-first UX).
    fireEvent.click(await screen.findByTestId('test-call-text-toggle'))
    const input = (await screen.findByTestId('test-call-input')) as HTMLInputElement
    await waitFor(() => expect(input.disabled).toBe(false))
    fireEvent.change(input, { target: { value: 'ping' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(sendUserTextMock).toHaveBeenCalledWith('ping')
    expect(screen.getByTestId('test-call-transcript')).toHaveTextContent('ping')
  })

  it('End button hangs up + closes status; close button invokes onClose', async () => {
    const onClose = vi.fn()
    render(withRouter(<TestCallPanel agentId="ag_1" onClose={onClose} />))
    await waitFor(() => expect(lastClient).not.toBeNull())
    client().opts.onEvent({ type: 'open' })
    fireEvent.click(await screen.findByTestId('test-call-end'))
    expect(hangupMock).toHaveBeenCalled()
    expect(screen.getByTestId('test-call-status')).toHaveAttribute('data-status', 'closed')
    fireEvent.click(screen.getByTestId('test-call-close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('error event surfaces server error message', async () => {
    render(withRouter(<TestCallPanel agentId="ag_1" onClose={() => {}} />))
    await waitFor(() => expect(lastClient).not.toBeNull())
    client().opts.onEvent({ type: 'error', error: 'connection refused' })
    await waitFor(() =>
      expect(screen.getByTestId('test-call-status')).toHaveAttribute('data-status', 'error'),
    )
    expect(screen.getByText(/connection refused/)).toBeInTheDocument()
  })
})
