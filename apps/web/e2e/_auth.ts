import type { Page } from '@playwright/test'

/**
 * Pretend the user is signed in for every page-level fetch.
 *
 * The dashboard now gates every route on a real session cookie (see
 * AuthGate in apps/web/src/app/AuthGate.tsx). Most E2E specs mock the
 * data endpoints but don't talk to a live API, so we also need a fake
 * /v1/auth/me response — otherwise the gate redirects every test to
 * /signin and nothing under Shell ever renders.
 *
 * Call this from each spec's `beforeEach` before navigating.
 */
export async function mockAuthed(page: Page) {
  await page.route('**/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: {
          id: 'usr_e2e',
          email: 'e2e@example.com',
          name: 'E2E Tester',
          avatar_url: null,
        },
        org: { id: 'org_e2e', name: 'E2E', slug: 'e2e' },
      }),
    }),
  )
}
