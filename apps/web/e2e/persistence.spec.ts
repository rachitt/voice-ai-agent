import { expect, test, type Route } from '@playwright/test'
import type { BuilderHandle } from './_builder-handle'
import { mockAuthed } from './_auth'

const API_BASE = 'http://localhost:8000'

type Json = Record<string, unknown>

function makeAgent(id: string, name: string, flowGraph: Json | null = null) {
  return {
    id,
    name,
    published_version_id: null,
    created_at: '2026-05-11T00:00:00Z',
    updated_at: '2026-05-11T00:00:00Z',
    versions: [
      {
        id: `${id}_v1`,
        version: 1,
        env: 'draft',
        first_message: 'Hi!',
        system_prompt: 'be brief',
        model_id: 'gemini/gemini-3.1-flash-lite',
        voice_id: '21m00Tcm4TlvDq8ikWAM',
        stt_id: 'deepgram-nova-3',
        language: 'en',
        interruption_sensitivity: 0.5,
        vad_silence_ms: 700,
        flow_graph: flowGraph,
        tools: [],
        knowledge_base_ids: [],
        analysis_plan: null,
        server_url: null,
        created_at: '2026-05-11T00:00:00Z',
      },
    ],
  }
}

test.describe('Builder ↔ API persistence', () => {
  test.beforeEach(async ({ context, page }) => {
    await context.addInitScript(({ base }) => {
      // localStorage only stores the non-credential API base preference now.
      localStorage.setItem('voice2.api_base', base)
    }, { base: API_BASE })
    await mockAuthed(page)
  })

  test('console lists agents from API and clicks through to builder', async ({ page }) => {
    await page.route(`${API_BASE}/v1/agents`, (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'ag_remote_1', name: 'Remote Agent A', published_version_id: null, created_at: '2026-05-11T00:00:00Z' },
        ]),
      }),
    )
    await page.route(`${API_BASE}/v1/agents/ag_remote_1`, (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeAgent('ag_remote_1', 'Remote Agent A')),
      }),
    )
    await page.route(`${API_BASE}/v1/agents/ag_remote_1`, (route) => route.fulfill({ status: 200, body: '{}' }), {
      times: 0,
    })

    await page.goto('/')
    await expect(page.getByTestId('agent-row-ag_remote_1')).toBeVisible()
    await page.getByTestId('agent-row-ag_remote_1').click()
    await expect(page).toHaveURL(/\/builder\/ag_remote_1$/)
    await expect(page.getByTestId('builder-agent-name')).toContainText('Remote Agent A')
  })

  test('builder hydrates flow_graph from API on mount', async ({ page }) => {
    const fg = {
      nodes: [
        { id: 'g', type: 'step', position: { x: 50, y: 50 }, data: { kind: 'greeting', title: 'Hello' } },
        { id: 'e', type: 'step', position: { x: 50, y: 200 }, data: { kind: 'end', title: 'Done' } },
      ],
      edges: [{ id: 'g->e', source: 'g', target: 'e', type: 'smoothstep' }],
    }
    await page.route(`${API_BASE}/v1/agents/ag_hydrate`, (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(makeAgent('ag_hydrate', 'Hydrated', fg)),
      }),
    )

    await page.goto('/builder/ag_hydrate')
    await expect(page.locator('[data-testid="step-node"][data-node-id="g"]')).toBeVisible()
    await expect(page.locator('[data-testid="step-node"][data-node-id="e"]')).toBeVisible()
    await expect(page.getByTestId('step-node')).toHaveCount(2)
  })

  test('autosave fires PATCH after a graph edit', async ({ page }) => {
    const fg = {
      nodes: [
        { id: 'g', type: 'step', position: { x: 0, y: 0 }, data: { kind: 'greeting', title: 'G' } },
        { id: 'e', type: 'step', position: { x: 0, y: 200 }, data: { kind: 'end', title: 'E' } },
      ],
      edges: [{ id: 'g->e', source: 'g', target: 'e', type: 'smoothstep' }],
    }
    await page.route(`${API_BASE}/v1/agents/ag_save`, (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeAgent('ag_save', 'Saver', fg)),
        })
      }
      // PATCH
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'ag_save_v2',
          version: 2,
          env: 'draft',
          first_message: 'Hi!',
          system_prompt: 'be brief',
          model_id: 'gemini/gemini-3.1-flash-lite',
          voice_id: '21m00Tcm4TlvDq8ikWAM',
          stt_id: 'deepgram-nova-3',
          language: 'en',
          interruption_sensitivity: 0.5,
          vad_silence_ms: 700,
          flow_graph: fg,
          tools: [],
          knowledge_base_ids: [],
          analysis_plan: null,
          server_url: null,
          created_at: '2026-05-11T00:00:00Z',
        }),
      })
    })

    await page.goto('/builder/ag_save')
    await expect(page.getByTestId('step-node')).toHaveCount(2)
    // Trigger an edit via store: add a collect node
    await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: BuilderHandle }).__voiceBuilder!
      s.getState().addNode('collect', { x: 100, y: 100 })
    })
    // Wait for autosave roundtrip (1500 ms debounce + req). Status may flick
    // past 'saving' too fast to catch in mocked mode — assert terminal state only.
    await expect(page.getByTestId('save-status')).toHaveAttribute('data-status', 'saved', {
      timeout: 5000,
    })
  })

  test('test call button opens modal and posts to /v1/calls/web', async ({ page }) => {
    const fg = {
      nodes: [
        { id: 'g', type: 'step', position: { x: 0, y: 0 }, data: { kind: 'greeting', title: 'G' } },
        { id: 'e', type: 'step', position: { x: 0, y: 200 }, data: { kind: 'end', title: 'E' } },
      ],
      edges: [{ id: 'g->e', source: 'g', target: 'e', type: 'smoothstep' }],
    }
    let postedAgent: string | null = null
    await page.route(`${API_BASE}/v1/agents/ag_call`, (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeAgent('ag_call', 'Caller', fg)),
        })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })
    await page.route(`${API_BASE}/v1/calls/web`, (route: Route) => {
      const body = JSON.parse(route.request().postData() || '{}') as { agent_id?: string }
      postedAgent = body.agent_id ?? null
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'call_test_1',
          agent_id: 'ag_call',
          direction: 'web',
          status: 'queued',
          ws_token: 'tok_x',
          ws_url: '/v1/calls/call_test_1/ws?token=tok_x',
        }),
      })
    })

    await page.goto('/builder/ag_call')
    await expect(page.getByTestId('builder-agent-name')).toContainText('Caller')

    await page.getByTestId('test-call').click()
    await expect(page.getByTestId('test-call-modal')).toBeVisible()
    await expect(page.getByTestId('test-call-status')).toBeVisible()

    // POST /v1/calls/web fired with the agent id
    await expect.poll(() => postedAgent, { timeout: 4000 }).toBe('ag_call')

    // Close modal
    await page.getByTestId('test-call-close').click()
    await expect(page.getByTestId('test-call-modal')).toHaveCount(0)
  })

  test('test call disabled until agent is loaded', async ({ page }) => {
    await page.goto('/builder/demo')
    await expect(page.getByTestId('test-call')).toBeDisabled()
  })

  test('publish surfaces 422 validator errors', async ({ page }) => {
    const fg = {
      nodes: [{ id: 'c', type: 'step', position: { x: 0, y: 0 }, data: { kind: 'collect', title: 'Only collect' } }],
      edges: [],
    }
    await page.route(`${API_BASE}/v1/agents/ag_bad`, (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeAgent('ag_bad', 'Bad', fg)),
        })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })
    await page.route(`${API_BASE}/v1/agents/ag_bad/publish`, (route: Route) =>
      route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            errors: ['graph must contain a greeting node'],
            warnings: [],
          },
        }),
      }),
    )

    await page.goto('/builder/ag_bad')
    await expect(page.getByTestId('builder-agent-name')).toContainText('Bad')
    await page.getByTestId('publish').click()
    await expect(page.getByTestId('publish-errors')).toBeVisible()
    await expect(page.getByTestId('publish-errors')).toContainText('greeting')
  })

  test('save-status pill opens dropdown with parsed analysis_plan errors', async ({ page }) => {
    const fg = {
      nodes: [
        { id: 'g', type: 'step', position: { x: 0, y: 0 }, data: { kind: 'greeting', title: 'G' } },
        { id: 'e', type: 'step', position: { x: 0, y: 200 }, data: { kind: 'end', title: 'E' } },
      ],
      edges: [{ id: 'g->e', source: 'g', target: 'e', type: 'smoothstep' }],
    }
    await page.route(`${API_BASE}/v1/agents/ag_err`, (route: Route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(makeAgent('ag_err', 'Errs', fg)),
        })
      }
      // PATCH → 422 with two analysis_plan errors
      return route.fulfill({
        status: 422,
        contentType: 'application/json',
        body: JSON.stringify({
          detail: {
            field: 'analysis_plan',
            errors: [
              'summary_prompt must be a string',
              'structured_data_schema must be an object',
            ],
          },
        }),
      })
    })

    await page.goto('/builder/ag_err')
    await expect(page.getByTestId('builder-agent-name')).toContainText('Errs')

    // Trigger autosave by editing the agent meta — easiest is to push a store
    // change that the autosave watcher picks up. We addNode to dirty the graph.
    await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: BuilderHandle }).__voiceBuilder!
      s.getState().addNode('collect', { x: 200, y: 200 })
    })

    // Pill enters error state w/ summarised count
    const pill = page.getByTestId('save-status')
    await expect(pill).toHaveAttribute('data-status', 'error', { timeout: 5000 })
    await expect(pill).toContainText('2 analysis_plan errors')

    // Closed initially
    await expect(page.getByTestId('save-error-list')).toHaveCount(0)

    // Click opens dropdown w/ both errors
    await pill.click()
    const list = page.getByTestId('save-error-list')
    await expect(list).toBeVisible()
    await expect(page.getByTestId('save-error-item')).toHaveCount(2)
    await expect(list).toContainText('summary_prompt must be a string')
    await expect(list).toContainText('structured_data_schema must be an object')

    // Click outside dismisses
    await page.locator('body').click({ position: { x: 5, y: 5 } })
    await expect(page.getByTestId('save-error-list')).toHaveCount(0)
  })
})
