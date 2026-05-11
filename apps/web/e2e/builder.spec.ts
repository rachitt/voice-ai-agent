import { expect, test } from '@playwright/test'

test.describe('Agent Builder', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/builder/demo')
    await expect(page.getByTestId('builder-root')).toBeVisible()
  })

  test('topbar shows name, env chip, tabs, version, test, publish', async ({ page }) => {
    await expect(page.getByTestId('builder-agent-name')).toContainText('Sales Qualifier Agent')
    await expect(page.getByTestId('builder-env-chip')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Builder' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Logs' })).toBeVisible()
    await expect(page.getByTestId('version-picker')).toBeVisible()
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
      'kb_lookup',
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

  test('click palette row adds node at viewport center', async ({ page }) => {
    const before = await page.getByTestId('step-node').count()
    await page.getByTestId('palette-row-transfer').click()
    await expect(page.getByTestId('step-node')).toHaveCount(before + 1)
    await expect(page.locator('[data-testid="step-node"][data-kind="transfer"]')).toHaveCount(1)
    // Newly added node is selected and inspector shows it
    await expect(page.getByTestId('inspector-title')).toHaveText('Transfer')
  })

  test('delete button removes selected node and its edges', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    await expect(page.getByTestId('inspector-title')).toHaveText('Greeting')
    const before = await page.getByTestId('step-node').count()
    await page.getByTestId('inspector-delete').click()
    await expect(page.getByTestId('step-node')).toHaveCount(before - 1)
    await expect(page.getByTestId('inspector-empty')).toBeVisible()
    // Edge greet->collect-name should be gone (zero edges from greet)
    await expect(page.locator('.react-flow__edge[data-id*="greet"]')).toHaveCount(0)
  })

  test('duplicate button clones selected node', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    const before = await page.getByTestId('step-node').count()
    await page.getByTestId('inspector-duplicate').click()
    await expect(page.getByTestId('step-node')).toHaveCount(before + 1)
    await expect(page.getByTestId('inspector-title')).toHaveText(/Greeting copy/)
  })

  test('title input renames the node header', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    await page.getByTestId('title-input').fill('Warm Welcome')
    await expect(greet).toContainText('Warm Welcome')
    await expect(page.getByTestId('inspector-title')).toHaveText('Warm Welcome')
  })

  test('keyboard delete (Backspace) removes selected node', async ({ page }) => {
    const target = page.locator('[data-testid="step-node"][data-node-id="vm"]')
    await target.click()
    await expect(target).toHaveAttribute('data-selected', '1')
    const before = await page.getByTestId('step-node').count()
    // ReactFlow listens on the pane; focus it first then dispatch
    await page.locator('.react-flow__pane').first().focus().catch(() => {})
    await page.keyboard.press('Backspace')
    await expect(page.getByTestId('step-node')).toHaveCount(before - 1)
  })

  test('rejects self-loop connection', async ({ page }) => {
    const before = await page.locator('.react-flow__edge').count()
    const err = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'greet', target: 'greet' })
      return s.getState().connectionError
    })
    expect(err).toMatch(/self-loop/i)
    await expect(page.getByTestId('connection-error')).toBeVisible()
    await expect(page.locator('.react-flow__edge')).toHaveCount(before)
  })

  test('rejects inbound to greeting', async ({ page }) => {
    const before = await page.locator('.react-flow__edge').count()
    const err = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'collect-name', target: 'greet' })
      return s.getState().connectionError
    })
    expect(err).toMatch(/cannot receive inbound/i)
    await expect(page.locator('.react-flow__edge')).toHaveCount(before)
  })

  test('rejects outbound from end (terminal)', async ({ page }) => {
    const before = await page.locator('.react-flow__edge').count()
    const err = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'end', target: 'greet' })
      return s.getState().connectionError
    })
    expect(err).toMatch(/terminal|outbound/i)
    await expect(page.locator('.react-flow__edge')).toHaveCount(before)
  })

  test('rejects 2nd outbound from linear node', async ({ page }) => {
    // greet already has 1 outbound (greet->collect-name). Adding a 2nd must fail.
    const before = await page.locator('.react-flow__edge').count()
    const err = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'greet', target: 'api' })
      return s.getState().connectionError
    })
    expect(err).toMatch(/outbound/i)
    await expect(page.locator('.react-flow__edge')).toHaveCount(before)
  })

  test('condition connect opens branch dialog; first label commits edge', async ({ page }) => {
    // Add a fresh collect node and try to connect from cond (which already has yes+no in seed).
    // Strategy: remove one existing condition edge first, then attempt a new connection.
    await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      const st = s.getState()
      // Delete the 'no' branch edge so we can re-open the dialog.
      st.onEdgesChange([{ id: 'cond->vm', type: 'remove' }])
    })

    await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'cond', target: 'vm' })
    })
    await expect(page.getByTestId('branch-dialog')).toBeVisible()
    // 'yes' is used → must be disabled
    await expect(page.getByTestId('branch-label-yes')).toBeDisabled()
    await page.getByTestId('branch-label-no').click()
    await expect(page.getByTestId('branch-dialog')).toHaveCount(0)
    // Edge added with label 'no'
    const labels = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      return s
        .getState()
        .edges.filter((e: any) => e.source === 'cond')
        .map((e: any) => e.label)
    })
    expect(labels).toEqual(expect.arrayContaining(['yes', 'no']))
  })

  test('condition rejects 3rd branch', async ({ page }) => {
    // Seed already has 2 outbound from cond. 3rd attempt must reject.
    const err = await page.evaluate(() => {
      const s = (window as unknown as { __voiceBuilder?: any }).__voiceBuilder!
      s.getState().onConnect({ source: 'cond', target: 'api' })
      return s.getState().connectionError
    })
    expect(err).toMatch(/outbound/i)
  })

  test('inspector shows in/out counts', async ({ page }) => {
    const greet = page.locator('[data-testid="step-node"][data-node-id="greet"]')
    await greet.click()
    await expect(page.getByTestId('conn-summary')).toContainText('in: 0')
    await expect(page.getByTestId('conn-summary')).toContainText('out: 1')
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
