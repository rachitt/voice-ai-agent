import { expect, test } from '@playwright/test'
import { mockAuthed } from './_auth'

test.describe('Numbers page', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthed(page)
    await page.goto('/numbers')
  })

  test('root + header render', async ({ page }) => {
    await expect(page.getByTestId('numbers-root')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Phone Numbers' })).toBeVisible()
  })

  test('new number form opens and validates E.164', async ({ page }) => {
    await page.getByTestId('new-number').click()
    const input = page.getByTestId('new-number-e164')
    await expect(input).toBeVisible()
    await input.fill('not-a-number')
    await page.getByTestId('confirm-new-number').click()
    // client-side validator surfaces the E.164 hint
    await expect(page.getByText('E.164 format required')).toBeVisible()
  })

  test('sidebar link routes here', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: /numbers/i }).first().click()
    await expect(page).toHaveURL(/\/numbers$/)
    await expect(page.getByTestId('numbers-root')).toBeVisible()
  })
})
