import { expect, test } from '@playwright/test'
import { mockAuthed } from './_auth'

test.describe('Analytics page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthed(page)
    await page.goto('/analytics')
  })

  test('root + stats cards render', async ({ page }) => {
    await expect(page.getByTestId('analytics-root')).toBeVisible()
    await expect(
      page.getByTestId('analytics-root').getByRole('heading', { name: 'Analytics' }),
    ).toBeVisible()
    for (const label of ['Total calls', 'Success rate', 'Avg duration', 'p95 duration']) {
      await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
  })

  test('range picker switches active selection', async ({ page }) => {
    await page.getByTestId('range-30d').click()
    await expect(page.getByTestId('range-30d')).toHaveClass(/bg-accent/)
    await page.getByTestId('range-7d').click()
    await expect(page.getByTestId('range-7d')).toHaveClass(/bg-accent/)
  })

  test('charts render section headers', async ({ page }) => {
    await expect(page.getByText('Call volume')).toBeVisible()
    await expect(page.getByText('Top agents')).toBeVisible()
  })
})
