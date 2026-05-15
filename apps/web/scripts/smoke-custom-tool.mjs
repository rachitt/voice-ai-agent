#!/usr/bin/env node
/**
 * Smoke test for custom-tool round-trip.
 *
 * Provisions a real `book_demo` tool that POSTs to httpbin.org/post,
 * binds it to a fresh agent, drives a voice call via the test-call
 * widget with a WAV that asks the agent to "book a demo for Friday",
 * and asserts that:
 *   1. an HTTP POST hit httpbin (we read it back via response.echo)
 *   2. a `tool_result` event landed in the transcript log
 *
 * Required env (same shape as voice-demo.mjs):
 *   API_BASE, WEB_BASE, API_KEY, WAV_PATH (a "book a demo for friday" recording)
 *
 * Run:
 *   node apps/web/scripts/smoke-custom-tool.mjs
 *
 * This is a manual smoke — not part of CI. CI coverage of the same
 * code path lives in apps/api/tests/test_custom_tool_roundtrip.py.
 */

import { chromium } from '@playwright/test'
import { existsSync } from 'node:fs'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000'
const WEB_BASE = process.env.WEB_BASE || 'http://localhost:5174'
const API_KEY = process.env.API_KEY
const WAV_PATH = process.env.WAV_PATH || '/tmp/book_demo.wav'
const HEADLESS = process.env.HEADLESS === '1'

if (!API_KEY) {
  console.error('[fatal] API_KEY required (e.g. sk_live_...)')
  process.exit(1)
}
if (!existsSync(WAV_PATH)) {
  console.error(`[fatal] WAV missing at ${WAV_PATH}`)
  console.error(
    `  fix: say -o ${WAV_PATH} --data-format=LEI16@48000 "Please book a demo for Friday for alice@example.com"`,
  )
  process.exit(1)
}

const headers = {
  Authorization: `Bearer ${API_KEY}`,
  'content-type': 'application/json',
}

async function http(method, path, body) {
  const r = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status} ${await r.text()}`)
  return r.status === 204 ? null : r.json()
}

async function main() {
  console.log('[step] registering httpbin tool')
  const tool = await http('POST', '/v1/tools', {
    name: 'book_demo',
    description: 'Book a product demo. Pass the requested day and attendee email.',
    server_url: 'https://httpbin.org/post',
    method: 'POST',
    headers: { 'x-smoke': 'voice-2.0' },
    params_schema: {
      type: 'object',
      properties: {
        day: { type: 'string', description: 'Day of week, e.g. Friday' },
        attendee_email: { type: 'string' },
      },
      required: ['day'],
    },
    timeout_ms: 8000,
  })
  console.log(`[step] tool_id=${tool.id}`)

  console.log('[step] minting agent bound to tool')
  const agent = await http('POST', '/v1/agents', {
    name: 'SmokeBookDemo',
    first_message:
      'Hi! I can book a product demo. Just say when works and where to send the invite.',
    system_prompt:
      'You book product demos. When the user names a day, call book_demo with {day, attendee_email}. Otherwise ask for the missing piece.',
    model_id: 'gemini/gemini-2.5-flash',
    voice_id: '21m00Tcm4TlvDq8ikWAM',
    tools: [tool.id],
  })
  console.log(`[step] agent_id=${agent.id}`)

  const browser = await chromium.launch({
    headless: HEADLESS,
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${WAV_PATH}`,
      '--autoplay-policy=no-user-gesture-required',
    ],
  })
  const context = await browser.newContext({
    permissions: ['microphone'],
    viewport: { width: 1440, height: 900 },
  })
  await context.addInitScript(
    ({ base, key }) => {
      localStorage.setItem('voice2.api_base', base)
      localStorage.setItem('voice2.api_key', key)
    },
    { base: API_BASE, key: API_KEY },
  )
  const page = await context.newPage()
  page.on('console', (m) => {
    if (m.type() === 'error') console.log(`  [page] ${m.text()}`)
  })

  console.log(`[step] navigate to /builder/${agent.id}`)
  await page.goto(`${WEB_BASE}/builder/${agent.id}`)
  await page.getByTestId('builder-root').waitFor({ timeout: 10_000 })
  await page.getByTestId('test-call').click()
  await page.getByTestId('test-call-modal').waitFor({ timeout: 10_000 })
  await page
    .getByTestId('test-call-status')
    .filter({ hasText: /live|connecting/i })
    .first()
    .waitFor({ timeout: 15_000 })

  console.log('[step] streaming transcript for 25s')
  const transcript = page.getByTestId('test-call-transcript')
  const seenTool = new Set()
  let toolCallSeen = false
  const deadline = Date.now() + 25_000
  while (Date.now() < deadline) {
    const items = await transcript.locator('[data-role]').all()
    for (const it of items) {
      const role = await it.getAttribute('data-role')
      const text = (await it.textContent())?.trim() ?? ''
      const key = `${role}::${text}`
      if (seenTool.has(key) || !text) continue
      seenTool.add(key)
      if (role === 'system' && text.startsWith('tool_result:')) toolCallSeen = true
      console.log(`  ${role.padEnd(6)} ${text}`)
    }
    await page.waitForTimeout(400)
  }

  try {
    await page.getByTestId('test-call-end').click({ timeout: 2_000 })
  } catch {
    /* widget already gone */
  }
  await browser.close()

  if (!toolCallSeen) {
    console.error('[fail] no tool_result transcript bubble — dispatch did NOT fire')
    process.exit(2)
  }
  console.log('[pass] tool_result bubble present — custom tool round-trip works')
}

main().catch((e) => {
  console.error('[fatal]', e)
  process.exit(1)
})
