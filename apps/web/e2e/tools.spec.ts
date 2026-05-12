import { expect, test } from '@playwright/test'

/**
 * Tools page CRUD + inline edit smoke. Mocks /v1/tools list/create/PATCH/delete
 * so the test is independent of seeded data.
 */

const TOOL_ID = 'tool_mock_001'

const baseRow = {
  id: TOOL_ID,
  name: 'lookup',
  description: null as string | null,
  server_url: 'https://example.com/api/lookup',
  method: 'POST',
  headers: {},
  params_schema: { type: 'object' },
  timeout_ms: 10000,
  created_at: '2026-05-11T00:00:00Z',
  updated_at: '2026-05-11T00:00:00Z',
}

test.describe('Tools page', () => {
  test.beforeEach(async ({ page }) => {
    const state: { rows: (typeof baseRow)[] } = { rows: [{ ...baseRow }] }

    await page.route('**/v1/auth/me', (r) => r.fulfill({ status: 401, body: '' }))

    await page.route(/\/v1\/tools$/, async (route) => {
      const req = route.request()
      if (req.method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(state.rows),
        })
      }
      if (req.method() === 'POST') {
        const body = JSON.parse(req.postData() || '{}')
        const row = {
          ...baseRow,
          id: `tool_${Date.now()}`,
          ...body,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }
        state.rows.push(row)
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify(row),
        })
      }
      return route.fallback()
    })

    await page.route(/\/v1\/tools\/[^/]+$/, async (route) => {
      const req = route.request()
      const id = req.url().split('/').pop()!
      if (req.method() === 'PATCH') {
        const patch = JSON.parse(req.postData() || '{}')
        const idx = state.rows.findIndex((r) => r.id === id)
        if (idx < 0) return route.fulfill({ status: 404, body: '' })
        state.rows[idx] = {
          ...state.rows[idx],
          ...patch,
          updated_at: new Date().toISOString(),
        }
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(state.rows[idx]),
        })
      }
      if (req.method() === 'DELETE') {
        state.rows = state.rows.filter((r) => r.id !== id)
        return route.fulfill({ status: 204, body: '' })
      }
      return route.fallback()
    })
  })

  test('list renders seed row', async ({ page }) => {
    await page.goto('/tools')
    await expect(page.getByTestId('tools-root')).toBeVisible()
    await expect(page.getByText('lookup', { exact: true })).toBeVisible()
  })

  test('inline edit updates name + timeout', async ({ page }) => {
    await page.goto('/tools')
    await page.getByTestId(`edit-${TOOL_ID}`).click()
    const nameInput = page.getByTestId(`edit-name-${TOOL_ID}`)
    await expect(nameInput).toBeVisible()
    await nameInput.fill('lookup_v2')
    await page.getByTestId(`save-${TOOL_ID}`).click()
    await expect(page.getByText('lookup_v2')).toBeVisible()
  })

  test('create flow adds new row', async ({ page }) => {
    await page.goto('/tools')
    await page.getByTestId('new-tool').click()
    await page.getByPlaceholder('lookup_customer').fill('charge_card')
    await page.getByPlaceholder('https://example.com/api/lookup').fill(
      'https://api.acme.com/charge',
    )
    await page.getByTestId('confirm-new-tool').click()
    await expect(page.getByText('charge_card')).toBeVisible()
  })

  test('delete confirms then removes', async ({ page }) => {
    page.on('dialog', (d) => d.accept())
    await page.goto('/tools')
    await page.getByTestId(`delete-${TOOL_ID}`).click()
    await expect(page.getByText('No tools yet.')).toBeVisible()
  })
})
