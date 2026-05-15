import { expect, test } from '@playwright/test'
import { mockAuthed } from './_auth'

/**
 * Calls page recording playback path.
 *
 * Mocks the call list + detail + recording-blob fetches so the test does not
 * depend on the live API having a real call w/ a real WAV.
 */

const CALL_ID = 'call_mocked_001'

const CALL_ROW = {
  id: CALL_ID,
  agent_id: 'ag_demo',
  direction: 'inbound',
  status: 'completed',
  from_number: '+15555550100',
  to_number: '+15555550200',
  started_at: '2026-05-11T20:00:00Z',
  ended_at: '2026-05-11T20:01:30Z',
  duration_ms: 90000,
  has_recording: true,
  created_at: '2026-05-11T20:00:00Z',
}

const CALL_DETAIL = {
  ...CALL_ROW,
  transcript: [
    { role: 'agent', text: 'Hi there!' },
    { role: 'user', text: 'Hi, I need help.' },
  ],
  provider_call_id: null,
  phone_number_id: null,
  analysis: null,
  dynamic_variables: {},
  recording_s3_key: 'kb/foo/bar.wav',
}

// 44-byte RIFF/WAVE header for an empty PCM file. Audio element accepts it.
const WAV_HEADER = Buffer.from([
  0x52, 0x49, 0x46, 0x46, 0x24, 0x00, 0x00, 0x00, 0x57, 0x41, 0x56, 0x45,
  0x66, 0x6d, 0x74, 0x20, 0x10, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
  0x40, 0x1f, 0x00, 0x00, 0x80, 0x3e, 0x00, 0x00, 0x02, 0x00, 0x10, 0x00,
  0x64, 0x61, 0x74, 0x61, 0x00, 0x00, 0x00, 0x00,
])

test.describe('Calls page — recording playback', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthed(page)
    await page.route(/\/v1\/calls(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [CALL_ROW],
          next_cursor: null,
          total: 1,
        }),
      }),
    )
    await page.route(`**/v1/calls/${CALL_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CALL_DETAIL),
      }),
    )
    // recording-url returns null url → frontend falls back to blob fetch
    await page.route(`**/v1/calls/${CALL_ID}/recording-url`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ url: null, expires_in: 600 }),
      }),
    )
    await page.route(`**/v1/calls/${CALL_ID}/recording`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'audio/wav',
        body: WAV_HEADER,
      }),
    )
  })

  test('row click loads detail, audio element + download appear', async ({ page }) => {
    await page.goto('/calls')
    const row = page.getByTestId(`call-row-${CALL_ID}`)
    await expect(row).toBeVisible()
    await row.click()
    await expect(page.getByTestId(`call-detail-${CALL_ID}`)).toBeVisible()
    await expect(page.getByTestId('audio')).toBeVisible()
    await expect(page.getByTestId('download-recording')).toBeVisible()
  })

  test('audio element has a blob src', async ({ page }) => {
    await page.goto('/calls')
    await page.getByTestId(`call-row-${CALL_ID}`).click()
    const audio = page.getByTestId('audio')
    await expect(audio).toBeVisible()
    const src = await audio.getAttribute('src')
    expect(src).toMatch(/^blob:/)
  })

  test('transcript renders mock lines', async ({ page }) => {
    await page.goto('/calls')
    await page.getByTestId(`call-row-${CALL_ID}`).click()
    await expect(page.getByText('Hi there!')).toBeVisible()
    await expect(page.getByText('Hi, I need help.')).toBeVisible()
  })
})

test.describe('Calls page — presigned URL path', () => {
  test('audio src uses presigned URL when available', async ({ page }) => {
    await mockAuthed(page)
    await page.route(/\/v1\/calls(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [CALL_ROW], next_cursor: null, total: 1 }),
      }),
    )
    await page.route(`**/v1/calls/${CALL_ID}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CALL_DETAIL),
      }),
    )
    const presigned = 'https://example.com/presigned.wav?sig=abc'
    await page.route(`**/v1/calls/${CALL_ID}/recording-url`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ url: presigned, expires_in: 600 }),
      }),
    )
    // Should never be hit when presigned URL is returned.
    let blobHit = false
    await page.route(`**/v1/calls/${CALL_ID}/recording`, (route) => {
      blobHit = true
      return route.fulfill({ status: 500, body: 'should not be called' })
    })

    await page.goto('/calls')
    await page.getByTestId(`call-row-${CALL_ID}`).click()
    const audio = page.getByTestId('audio')
    await expect(audio).toHaveAttribute('src', presigned)
    expect(blobHit).toBe(false)
  })
})
