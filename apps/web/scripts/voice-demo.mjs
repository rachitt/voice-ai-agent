#!/usr/bin/env node
/**
 * Headed Playwright client that drives the full voice pipeline end to end
 * against a running backend + frontend, with a fake mic feeding a WAV.
 *
 * What you see:
 *   1. Chrome opens, navigates to the launch console
 *   2. Switches to the agent builder
 *   3. Opens the Test Call modal
 *   4. Fake mic streams WAV audio → Deepgram → Gemini → ElevenLabs → speakers
 *   5. Transcript bubbles fill in
 *
 * Requires: API at http://127.0.0.1:8000, web at http://localhost:5174,
 *   and `/tmp/voice_demo.wav` (48 kHz mono LE16 PCM).
 *
 * Run:
 *   node apps/web/scripts/voice-demo.mjs
 *
 * Env overrides:
 *   API_BASE=http://127.0.0.1:8000
 *   WEB_BASE=http://localhost:5174
 *   API_KEY=sk_live_...
 *   WAV_PATH=/tmp/voice_demo.wav
 *   AGENT_ID=ag_existing   (optional; otherwise script mints a new agent)
 *   HEADLESS=1             (optional; default is headed so you can watch)
 */

import { chromium } from '@playwright/test'
import { existsSync } from 'node:fs'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000'
const WEB_BASE = process.env.WEB_BASE || 'http://localhost:5174'
const API_KEY =
  process.env.API_KEY ||
  'REDACTED_API_KEY'
const WAV_PATH = process.env.WAV_PATH || '/tmp/voice_demo.wav'
const HEADLESS = process.env.HEADLESS === '1'

if (!existsSync(WAV_PATH)) {
  console.error(`[fatal] WAV not found at ${WAV_PATH}`)
  console.error(`  fix: say -o ${WAV_PATH} --data-format=LEI16@48000 "your test text"`)
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
  return r.json()
}

async function mintAgent() {
  console.log('[step] minting agent via API')
  const ag = await http('POST', '/v1/agents', {
    name: 'PlaywrightDemo',
    first_message:
      'Hi there! This is a live test. Ask me anything in one sentence.',
    system_prompt:
      'You are a friendly demo voice agent. Reply briefly in one or two short sentences.',
    model_id: 'gemini/gemini-2.5-flash', // 3.1-flash-lite is rate-limited right now
    voice_id: '21m00Tcm4TlvDq8ikWAM',
  })
  console.log(`[step] agent_id=${ag.id}`)
  return ag.id
}

function dim(s) {
  return `\x1b[2m${s}\x1b[0m`
}

async function main() {
  const agentId = process.env.AGENT_ID || (await mintAgent())

  console.log('[step] launching chromium (headed)')
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

  // Seed API key + base before any page script runs.
  await context.addInitScript(
    ({ base, key }) => {
      localStorage.setItem('voice2.api_base', base)
      localStorage.setItem('voice2.api_key', key)
    },
    { base: API_BASE, key: API_KEY },
  )

  const page = await context.newPage()

  // Surface page console errors to our terminal so you can see what's happening.
  page.on('console', (m) => {
    if (m.type() === 'error') console.log(dim(`  [page.error] ${m.text()}`))
  })
  page.on('pageerror', (e) => console.log(dim(`  [page.error] ${e.message}`)))

  // 1. Console
  console.log('[step] open launch console')
  await page.goto(`${WEB_BASE}/`)
  await page.getByTestId('console-root').waitFor({ timeout: 10_000 })
  await page.waitForTimeout(1200)

  // 2. Builder
  console.log(`[step] navigate to /builder/${agentId}`)
  await page.goto(`${WEB_BASE}/builder/${agentId}`)
  await page.getByTestId('builder-root').waitFor({ timeout: 10_000 })
  await page.waitForTimeout(1500)

  // 3. Open Test Call modal
  console.log('[step] click Test Call')
  await page.getByTestId('test-call').click()
  const modal = page.getByTestId('test-call-modal')
  await modal.waitFor({ timeout: 10_000 })

  // 4. Wait for status to flip to "live", then let mic stream in.
  console.log('[step] waiting for WS connection (status=live)')
  await page
    .getByTestId('test-call-status')
    .filter({ hasText: /live|connecting/i })
    .first()
    .waitFor({ timeout: 15_000 })

  // 5. Tail transcript bubbles for 20s and print them as they appear.
  console.log('[step] streaming transcript:')
  const transcript = page.getByTestId('test-call-transcript')
  const seen = new Set()
  const deadline = Date.now() + 25_000
  while (Date.now() < deadline) {
    const items = await transcript.locator('[data-role]').all()
    for (const it of items) {
      const role = await it.getAttribute('data-role')
      const text = (await it.textContent())?.trim() ?? ''
      const key = `${role}::${text}`
      if (!seen.has(key) && text) {
        seen.add(key)
        const tag =
          role === 'user' ? '🎤 user   ' : role === 'agent' ? '🤖 agent  ' : '⚙️  system '
        console.log(`  ${tag} ${text}`)
      }
    }
    await page.waitForTimeout(400)
  }

  // 6. Hang up cleanly.
  console.log('[step] hanging up')
  try {
    await page.getByTestId('test-call-end').click({ timeout: 2_000 })
  } catch {
    /* modal may have closed */
  }

  // 7. Leave the browser visible briefly so you can see the final state.
  if (!HEADLESS) {
    console.log('[step] holding browser open 5s so you can see the result')
    await page.waitForTimeout(5_000)
  }

  await browser.close()
  console.log('[done]')
}

main().catch((e) => {
  console.error('[fatal]', e)
  process.exit(1)
})
