# Next Session — M1 Dashboard UI Completion

Picks up where session ending 2026-05-11 left off. All M1 pages currently
return `<Placeholder title="X" />` from `apps/web/src/app/router.tsx`. Backend
CRUD endpoints already exist; this milestone is mostly frontend.

Estimated total: 1-2 days. Order chosen so each task lands a fully working
page without blocking on the next.

## Repo state at session start

- Branch: `main`, fully committed.
- Backend: 149 tests passing.
- Done routes: `Calls`, `Settings`, `Web Call`, `Launch Console`, `Builder`.
- TODO routes: `Numbers`, `Knowledge`, `Tools`, `Analytics`.
- API client lives at `apps/web/src/lib/api.ts` (Bearer auth via localStorage).

## Backend endpoint inventory (already shipped)

| Route                           | What it does                          |
|--------------------------------|---------------------------------------|
| `GET/POST /v1/phone-numbers`    | List + create phone numbers           |
| `PATCH /v1/phone-numbers/{id}`  | Update `agent_id`, `status`           |
| `GET/POST/DELETE /v1/tools`     | Custom tool CRUD                      |
| `GET/POST /v1/knowledge-bases`  | KB CRUD                               |
| `POST /v1/knowledge-bases/{id}/sources` | Add source (text/url/s3)      |
| `POST /v1/knowledge-bases/{id}/sources/upload` | multipart upload       |
| `GET /v1/calls?...`             | Paginated call list (cursor + filters)|

Schemas: `apps/api/app/schemas/{phone_numbers,tools,knowledge_bases,calls}.py`.

## Task 1 — Numbers page (~2-3 hours)

**Why first**: smallest surface (single CRUD list), proves the pattern.

1. `apps/web/src/lib/api.ts` — add `phoneNumbers` block:
   ```ts
   export const phoneNumbers = {
     list:   () => req<PhoneNumber[]>(`/v1/phone-numbers`),
     create: (body: PhoneNumberCreate) => req<PhoneNumber>(`/v1/phone-numbers`, {...}),
     update: (id, body: PhoneNumberUpdate) => req<PhoneNumber>(...),
   }
   ```
2. Create `apps/web/src/pages/numbers/index.tsx` modelled on
   `apps/web/src/pages/settings/index.tsx` (already has list + create +
   inline edit pattern that fits here perfectly).
3. Per-row controls: bind to agent (dropdown from `api.listAgents()`), set
   status active/disabled, copy E.164 to clipboard.
4. Route wire-up in `apps/web/src/app/router.tsx`: replace
   `<Placeholder title="Numbers" />` with `<NumbersPage />`.
5. Smoke-test: `pnpm build` clean. No backend changes expected.

## Task 2 — Tools page (~2-3 hours)

Same shape as Numbers, but the schema field is richer:
`server_url`, `method`, `headers`, `params_schema` (JSON), `timeout_ms`.

1. `apps/web/src/pages/tools/index.tsx`:
   - List rows: name, method+url, timeout, last_used (not exposed yet —
     add column ONLY if you also extend backend `ToolOut`).
   - Create modal with form for all fields; `params_schema` as JSON
     textarea with `JSON.parse` guard (mirror builder's approach).
   - Delete confirm.
2. Wire `tools: { list, create, update?, delete }` to `lib/api.ts`. **Note**:
   backend has no PATCH for tools today — either add one
   (`apps/api/app/routers/tools.py`, follow `phone_numbers.py` shape) OR
   ship list+create+delete only and call this out in the UI.
3. Tool entries surface in builder's tool palette via `ver.tools` — that
   path already works, no builder changes needed.

## Task 3 — Knowledge page (~3-4 hours)

Larger because of file upload. Backend already has the multipart endpoint
+ arq ingest worker (`apps/api/app/workers/kb_ingest.py`).

1. Two-pane layout matching Calls page: KB list on left, KB detail on right.
2. Left pane: `kbList()` → name + embedding_model + created_at.
3. Right pane: KB header + Sources list. Each source row:
   - name, kind chip (pdf/txt/md/docx/url)
   - status chip with tone: `queued`/`ingesting`=warn, `ready`=accent,
     `error`=danger
   - if status=error, show `error` text on click
4. Upload control: `<input type=file>` → `FormData` to
   `/v1/knowledge-bases/{kb_id}/sources/upload`. Poll list every 3s while any
   source is non-terminal (queued/ingesting).
5. Add a "Test query" panel that POSTs to the kb_lookup tool endpoint with
   a typed query → shows top-K hits with scores. Wire it through the same
   API key, NOT a special debug endpoint.

Gotchas:
- The upload endpoint may require `enable_object_store=true`. Show a banner
  + disable upload control when the GET `/healthz` or KB list returns
  "uploads disabled". Cheaper: just attempt, catch 503, surface message.
- arq worker needs to be running for status to advance past `queued`.
  Document this in the page's empty state.

## Task 4 — Analytics page (~3-4 hours)

`recharts` is already in the bundle (charts vendor chunk). Use it.

1. New backend endpoint (this is the only backend change in M1):
   `GET /v1/console/analytics?range=7d|30d|90d` returning:
   ```json
   {
     "range": "7d",
     "volume_by_day": [{"date": "2026-05-04", "count": 12, "completed": 10, "failed": 2}, ...],
     "by_agent": [{"agent_id": "ag_x", "name": "Support", "count": 42, "success_rate": 0.87}, ...],
     "avg_duration_ms": 187432,
     "p50_duration_ms": 142000,
     "p95_duration_ms": 412000,
     "success_rate": 0.83
   }
   ```
   Put it next to `apps/api/app/routers/console.py:summary`. Aggregate via
   SQL (`date_trunc('day', created_at)`, `count(*) filter where status=...`).
   Pull success rate from `call.analysis.success_evaluation.success` when
   present, else treat `status=completed` as success.
2. Test it (`apps/api/tests/test_console.py` already exists, follow
   pattern).
3. Frontend: `apps/web/src/pages/analytics/index.tsx`:
   - Range selector (7d/30d/90d)
   - Top stats row: total calls, success %, avg duration, p95 duration
   - LineChart: volume_by_day (completed vs failed stacked)
   - BarChart: top agents by volume + success rate
4. Reuse the chip + panel styles from Calls page.

## Cross-cutting cleanup

- Remove the `<Placeholder>` component from `router.tsx` once all four
  routes have real pages.
- Add e2e smoke tests to `apps/web/e2e/` for at least one of the new pages
  (Playwright config is already set up).
- Run `pnpm build` and verify chunk sizes didn't regress past 500 KB.

## Open questions to confirm before coding

None — endpoints are stable, schemas are typed, design tokens exist. Ship.

## Stretch goals if M1 finishes early

1. Builder: `analysis_plan` editor pane (JSON form for `summary_prompt`,
   `structured_data_schema`, `success_prompt`). Today it can only be set
   via API.
2. Builder: dynamic_variables form on agent + on-call-create overrides in
   the Test Call modal.
3. Pull e2e test scaffolding for Calls page since the recording playback
   path is currently untested through Playwright.

## Definition of done for M1

- [ ] Numbers page lists, creates, updates phone numbers
- [ ] Tools page lists, creates, deletes tools
- [ ] Knowledge page lists KBs + sources, uploads files, polls status
- [ ] Analytics page renders 4 cards + 2 charts from real `/v1/console/analytics`
- [ ] All four sidebar links land on real pages, not placeholders
- [ ] `pnpm build` clean, no new chunk-size warnings
- [ ] `uv run pytest` clean (149+ tests pass)
- [ ] Commit messages follow the short-and-simple style from
      `feedback_commits.md`
