import { expect, test } from '@playwright/test'

test.describe('Launch Console', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await expect(page.getByTestId('console-root')).toBeVisible()
  })

  test('panels all mount', async ({ page }) => {
    for (const id of [
      'checklist',
      'simulator',
      'transcript',
      'tool-calls',
      'today',
      'score-gauge',
      'compliance',
      'launch-history',
    ]) {
      await expect(page.getByTestId(id)).toBeVisible()
    }
  })

  test('deployment checklist has 3 done + 1 current + 2 todo', async ({ page }) => {
    const checklist = page.getByTestId('checklist')
    await expect(checklist.locator('[data-status="done"]')).toHaveCount(3)
    await expect(checklist.locator('[data-status="current"]')).toHaveCount(1)
    await expect(checklist.locator('[data-status="todo"]')).toHaveCount(2)
  })

  test('transcript shows demo seed when no call is being watched', async ({ page }) => {
    const bubbles = page.getByTestId('bubble')
    await expect(bubbles).toHaveCount(6)
    await expect(page.getByTestId('demo-chip')).toBeVisible()
    await expect(bubbles.first()).toHaveAttribute('data-who', 'agent')
    await expect(page.getByTestId('watch-call-input')).toBeVisible()
  })

  test('tool calls show mixed statuses', async ({ page }) => {
    const rows = page.getByTestId('tool-call-row')
    await expect(rows).toHaveCount(5)
    await expect(rows.filter({ hasText: 'lookup_account' })).toHaveAttribute(
      'data-status',
      'success',
    )
    await expect(rows.filter({ hasText: 'send_email' })).toHaveAttribute(
      'data-status',
      'failed',
    )
  })

  test('score gauge renders SVG with 92', async ({ page }) => {
    const gauge = page.getByTestId('score-gauge')
    await expect(gauge.locator('svg')).toBeVisible()
    await expect(gauge.getByText('92', { exact: true })).toBeVisible()
  })

  test('today metrics visible', async ({ page }) => {
    const today = page.getByTestId('today')
    await expect(today.getByText('$46')).toBeVisible()
    await expect(today.getByText('$68')).toBeVisible()
    await expect(today.getByText('480 minutes')).toBeVisible()
  })

  test('launch test button clickable', async ({ page }) => {
    await expect(page.getByTestId('launch-test')).toBeEnabled()
  })

  test('open builder navigates to /builder/demo', async ({ page }) => {
    await page.getByTestId('open-builder').click()
    await expect(page).toHaveURL(/\/builder\/demo$/)
    await expect(page.getByTestId('builder-root')).toBeVisible()
  })

  test('no console errors', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text())
    })
    await page.reload()
    await page.waitForTimeout(3000)
    expect(errors).toEqual([])
  })

  test('unknown route redirects to /', async ({ page }) => {
    await page.goto('/does-not-exist')
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('console-root')).toBeVisible()
  })
})
