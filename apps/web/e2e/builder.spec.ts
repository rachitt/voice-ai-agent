import { expect, test } from '@playwright/test'

test.describe('Agent Builder', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/builder/demo')
    await expect(page.getByTestId('builder-root')).toBeVisible()
  })

  test('topbar shows name, env chip, tabs, version, test, publish', async ({ page }) => {
    await expect(page.getByText('Sales Qualifier Agent')).toBeVisible()
    await expect(page.getByText('Production')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Builder' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Logs' })).toBeVisible()
    await expect(page.getByText('Version 12')).toBeVisible()
    await expect(page.getByTestId('test-call')).toBeVisible()
    await expect(page.getByTestId('publish')).toBeVisible()
  })

  test('palette lists all core blocks + integrations', async ({ page }) => {
    const palette = page.getByTestId('palette')
    for (const kind of [
      'greeting',
      'collect',
      'api',
      'condition',
      'transfer',
      'voicemail',
      'end',
      'sheets',
      'salesforce',
    ]) {
      await expect(palette.locator(`[data-testid="palette-row-${kind}"]`)).toBeVisible()
    }
  })

  test('canvas renders seed graph of 7 nodes', async ({ page }) => {
    await expect(page.getByTestId('step-node')).toHaveCount(7)
  })

  test('inspector populates from default selection', async ({ page }) => {
    const inspector = page.getByTestId('inspector')
    await expect(inspector).toBeVisible()
    await expect(page.getByTestId('inspector-title')).toHaveText(/Collect Info/i)
  })

  test('clicking node selects it, click empty deselects', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    await expect(greet).toHaveAttribute('data-selected', '1')
    await expect(page.getByTestId('inspector-title')).toHaveText('Greeting')

    // Click ReactFlow pane background (an area outside any node)
    const pane = page.locator('.react-flow__pane').first()
    await pane.click({ position: { x: 10, y: 10 } })
    await expect(page.getByTestId('inspector-empty')).toBeVisible()
  })

  test('editing prompt updates node subtitle live', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    const input = page.getByTestId('prompt-input')
    await input.fill('Howdy partner!')
    await expect(greet).toContainText('Howdy partner!')
  })

  test('retry policy toggle activates exclusively', async ({ page }) => {
    await page.locator('[data-testid="step-node"][data-node-id="greet"]').click()
    await page.getByTestId('retry-linear').click()
    await expect(page.getByTestId('retry-linear')).toHaveAttribute('data-active', '1')
    await expect(page.getByTestId('retry-exponential')).toHaveAttribute('data-active', '0')
  })

  test('palette search filters', async ({ page }) => {
    await page.getByTestId('palette-search').fill('api')
    await expect(page.getByTestId('palette-row-api')).toBeVisible()
    await expect(page.getByTestId('palette-row-greeting')).toHaveCount(0)
  })

  test('back arrow returns to console', async ({ page }) => {
    await page.getByTestId('back-to-console').click()
    await expect(page).toHaveURL(/\/$/)
    await expect(page.getByTestId('console-root')).toBeVisible()
  })

  test('drag from palette adds new node to canvas', async ({ page }) => {
    // ReactFlow drop handler reads dataTransfer set by palette dragstart.
    // Simulate via dispatchEvent because Playwright drag chain doesn't relay dataTransfer in headless.
    const before = await page.getByTestId('step-node').count()

    const handle = await page.locator('[data-testid="palette-row-transfer"]').elementHandle()
    const pane = await page.locator('.react-flow__pane').first().elementHandle()
    if (!handle || !pane) throw new Error('missing target elements')

    await page.evaluate(
      ({ from, to }) => {
        const dt = new DataTransfer()
        dt.setData('application/voice-step', 'transfer')

        from.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }))
        const box = (to as HTMLElement).getBoundingClientRect()
        const x = box.left + 200
        const y = box.top + 200
        to.dispatchEvent(
          new DragEvent('dragover', { bubbles: true, dataTransfer: dt, clientX: x, clientY: y }),
        )
        to.dispatchEvent(
          new DragEvent('drop', { bubbles: true, dataTransfer: dt, clientX: x, clientY: y }),
        )
      },
      { from: handle, to: pane },
    )

    await expect(page.getByTestId('step-node')).toHaveCount(before + 1)
    await expect(page.locator('[data-testid="step-node"][data-kind="transfer"]')).toHaveCount(1)
  })
})
