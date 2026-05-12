import { useCallback, useEffect, useRef, useState } from 'react'
import { BookOpen, FileText, Plus, RefreshCw, Search, Upload } from 'lucide-react'
import {
  knowledgeBases,
  type KbQueryHit,
  type KbSource,
  type KnowledgeBase,
} from '@/lib/api'
import { cn } from '@/lib/cn'
import { ApiErrorBanner } from '@/components/ApiErrorBanner'

const NON_TERMINAL = new Set(['queued', 'ingesting'])

export function KnowledgePage() {
  const [kbs, setKbs] = useState<KnowledgeBase[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [sources, setSources] = useState<KbSource[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const pollRef = useRef<number | null>(null)

  const loadKbs = useCallback(async () => {
    setErr(null)
    try {
      const list = await knowledgeBases.list()
      setKbs(list)
      if (!selected && list.length > 0) setSelected(list[0].id)
    } catch (e) {
      setErr(String(e))
      setKbs([])
    }
  }, [selected])

  const loadSources = useCallback(async (kbId: string) => {
    try {
      const list = await knowledgeBases.listSources(kbId)
      setSources(list)
      return list
    } catch (e) {
      setErr(String(e))
      return []
    }
  }, [])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial KB list fetch on mount
    void loadKbs()
  }, [loadKbs])

  useEffect(() => {
    if (!selected) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- clear sources when KB deselected
      setSources([])
      return
    }
    void loadSources(selected)
  }, [selected, loadSources])

  // poll while any source is non-terminal
  useEffect(() => {
    if (!selected) return
    const hasPending = sources.some((s) => NON_TERMINAL.has(s.status))
    if (!hasPending) {
      if (pollRef.current) {
        window.clearTimeout(pollRef.current)
        pollRef.current = null
      }
      return
    }
    pollRef.current = window.setTimeout(() => {
      void loadSources(selected)
    }, 3000)
    return () => {
      if (pollRef.current) {
        window.clearTimeout(pollRef.current)
        pollRef.current = null
      }
    }
  }, [sources, selected, loadSources])

  async function onCreateKb() {
    if (!newName.trim()) return
    setBusy(true)
    setErr(null)
    try {
      const kb = await knowledgeBases.create({ name: newName.trim() })
      setNewName('')
      setShowNew(false)
      setSelected(kb.id)
      await loadKbs()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function onUpload(file: File) {
    if (!selected) return
    setUploading(true)
    setErr(null)
    try {
      await knowledgeBases.uploadSource(selected, file)
      await loadSources(selected)
    } catch (e) {
      setErr(String(e))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="flex h-full min-h-0 gap-4" data-testid="knowledge-root">
      <section className="panel flex min-h-0 w-[320px] shrink-0 flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-muted" />
            <h2 className="text-sm font-medium">Knowledge Bases</h2>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={loadKbs}
              className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
              title="Refresh"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
            <button
              data-testid="new-kb"
              onClick={() => setShowNew((v) => !v)}
              className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
              title="New KB"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </header>

        {showNew && (
          <div className="flex items-center gap-2 border-b border-border bg-panel-2 px-4 py-3">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Name (e.g. product-docs)"
              className="flex-1 rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
              onKeyDown={(e) => {
                if (e.key === 'Enter') void onCreateKb()
                if (e.key === 'Escape') {
                  setShowNew(false)
                  setNewName('')
                }
              }}
            />
            <button
              disabled={busy || !newName.trim()}
              onClick={onCreateKb}
              className="rounded-[6px] bg-accent px-2 py-1.5 text-xs text-bg disabled:opacity-40"
            >
              Add
            </button>
          </div>
        )}

        <ul className="min-h-0 flex-1 overflow-auto" data-testid="kb-list">
          {kbs === null ? (
            <li className="px-4 py-6 text-sm text-muted">Loading…</li>
          ) : kbs.length === 0 ? (
            <li className="px-4 py-6 text-sm text-muted">No KBs yet.</li>
          ) : (
            kbs.map((kb) => (
              <li key={kb.id}>
                <button
                  data-testid={`kb-${kb.id}`}
                  onClick={() => setSelected(kb.id)}
                  className={cn(
                    'block w-full border-l-2 px-4 py-3 text-left text-sm transition-colors',
                    selected === kb.id
                      ? 'border-accent bg-panel-2 text-fg'
                      : 'border-transparent text-muted hover:bg-panel-2 hover:text-fg',
                  )}
                >
                  <div className="font-medium">{kb.name}</div>
                  <div className="mt-0.5 text-[11px] text-muted">
                    {kb.embedding_model}
                  </div>
                </button>
              </li>
            ))
          )}
        </ul>
      </section>

      <section className="panel flex min-h-0 flex-1 flex-col">
        <ApiErrorBanner err={err} variant="stripe" />

        {!selected ? (
          <div className="grid flex-1 place-items-center text-sm text-muted">
            Select or create a knowledge base.
          </div>
        ) : (
          <>
            <header className="flex items-center justify-between border-b border-border px-5 py-3">
              <div className="flex items-center gap-2">
                <FileText className="h-4 w-4 text-muted" />
                <h3 className="text-sm font-medium">Sources</h3>
                <span className="text-[11px] text-muted">{sources.length}</span>
              </div>
              <div className="flex items-center gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  hidden
                  accept=".txt,.md,.pdf,.docx"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) void onUpload(f)
                  }}
                />
                <button
                  data-testid="upload-source"
                  disabled={uploading}
                  onClick={() => fileRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs hover:bg-bg disabled:opacity-40"
                >
                  <Upload className="h-3.5 w-3.5" />
                  {uploading ? 'Uploading…' : 'Upload file'}
                </button>
              </div>
            </header>

            <ul className="min-h-0 flex-1 divide-y divide-border overflow-auto">
              {sources.length === 0 ? (
                <li className="px-5 py-8 text-sm text-muted">
                  No sources yet. Upload a PDF/MD/DOCX/TXT to ingest.
                  <div className="mt-1 text-[11px]">
                    Status advances past <code>queued</code> only when the arq KB
                    worker is running.
                  </div>
                </li>
              ) : (
                sources.map((s) => (
                  <li
                    key={s.id}
                    className="flex items-center justify-between gap-3 px-5 py-3 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{s.name}</span>
                        <span className="chip text-muted">{s.kind}</span>
                      </div>
                      {s.error && (
                        <div className="mt-1 break-all text-[11px] text-danger">
                          {s.error}
                        </div>
                      )}
                    </div>
                    <StatusChip status={s.status} />
                  </li>
                ))
              )}
            </ul>
            <KbQueryPanel kbId={selected} />
          </>
        )}
      </section>
    </div>
  )
}

function KbQueryPanel({ kbId }: { kbId: string }) {
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<KbQueryHit[] | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [lastQuery, setLastQuery] = useState('')

  // Reset state when the selected KB changes.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- kbId switch must clear query inputs/results
    setQuery('')
    setHits(null)
    setErr(null)
    setElapsedMs(null)
    setLastQuery('')
  }, [kbId])

  async function run() {
    if (!query.trim()) return
    setBusy(true)
    setErr(null)
    try {
      const q = query.trim()
      const res = await knowledgeBases.query(kbId, { query: q, top_k: 5 })
      setHits(res.hits)
      setElapsedMs(res.elapsed_ms ?? 0)
      setLastQuery(q)
    } catch (e) {
      setErr(String(e))
      setHits([])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      data-testid="kb-query-panel"
      className="shrink-0 border-t border-border bg-panel-2 px-5 py-3"
    >
      <div className="mb-2 flex items-center gap-2">
        <Search className="h-3.5 w-3.5 text-muted" />
        <span className="text-[11px] uppercase tracking-wide text-muted">
          Test query
        </span>
      </div>
      <div className="flex items-center gap-2">
        <input
          data-testid="kb-query-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void run()
          }}
          placeholder="Ask something about this KB…"
          className="flex-1 rounded-[6px] border border-border bg-bg px-2 py-1.5 text-xs outline-none focus:border-accent"
        />
        <button
          data-testid="kb-query-go"
          disabled={busy || !query.trim()}
          onClick={run}
          className="rounded-[6px] bg-accent px-3 py-1.5 text-xs text-bg disabled:opacity-40"
        >
          {busy ? 'Searching…' : 'Search'}
        </button>
      </div>
      {err && (
        <div className="mt-2 text-[11px] text-danger">{err}</div>
      )}
      {hits !== null && (
        <>
          {elapsedMs !== null && (
            <div
              data-testid="kb-query-meta"
              className="mt-2 text-[10px] uppercase tracking-wide text-muted"
            >
              {hits.length} hit{hits.length === 1 ? '' : 's'} · {elapsedMs}ms
            </div>
          )}
          <ul
            data-testid="kb-query-hits"
            className="mt-3 flex max-h-48 flex-col gap-2 overflow-auto"
          >
            {hits.length === 0 ? (
              <li className="text-[11px] text-muted">No hits.</li>
            ) : (
              hits.map((h) => (
                <li
                  key={h.chunk_id}
                  className="rounded-[6px] border border-border bg-panel px-3 py-2 text-[11px]"
                >
                  <div className="mb-1 flex items-center justify-between">
                    <span className="truncate text-muted">
                      {h.source_name || h.source_id}
                    </span>
                    <span className="chip text-accent">
                      {h.score.toFixed(3)}
                    </span>
                  </div>
                  <div className="whitespace-pre-wrap text-fg">
                    {renderHighlighted(h.text, lastQuery)}
                  </div>
                </li>
              ))
            )}
          </ul>
        </>
      )}
    </div>
  )
}

/**
 * English stop words — never highlight these even if ≥3 chars.
 */
const STOP_WORDS = new Set([
  'the', 'and', 'for', 'with', 'that', 'this', 'from', 'are', 'was', 'were',
  'have', 'has', 'had', 'but', 'not', 'you', 'your', 'our', 'how', 'why',
  'who', 'what', 'when', 'where', 'which', 'into', 'about', 'over', 'they',
  'them', 'their', 'his', 'her', 'its', 'will', 'would', 'could', 'should',
])

/**
 * Reduce a token to a crude stem (last few suffixes stripped). Cheap
 * alternative to a full Porter stemmer — good enough for highlighting
 * "billing" when the user typed "bill".
 */
function stem(token: string): string {
  let t = token.toLowerCase()
  for (const suf of ['ingly', 'edly', 'ing', 'ied', 'ies', 'ed', 'es', 'ly', 's']) {
    if (t.length > suf.length + 2 && t.endsWith(suf)) {
      t = t.slice(0, -suf.length)
      break
    }
  }
  return t
}

function renderHighlighted(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text
  // Stem each query token. Match any word in `text` whose own stem starts
  // with — or is contained by — a query stem. This catches "bill" ↔
  // "billing", "ship" ↔ "shipped", "invoice" ↔ "invoices".
  const queryStems = query
    .split(/\s+/)
    .map((t) => t.toLowerCase().replace(/[^\p{L}\p{N}_]/gu, ''))
    .filter((t) => t.length >= 3 && !STOP_WORDS.has(t))
    .map(stem)
  if (queryStems.length === 0) return text

  const out: React.ReactNode[] = []
  let cursor = 0
  // Tokenize text into words + separators, preserving positions.
  const re = /[\p{L}\p{N}_]+/gu
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    const word = m[0]
    const start = m.index
    if (start > cursor) out.push(<span key={`s${start}`}>{text.slice(cursor, start)}</span>)
    const ws = stem(word)
    const hit = queryStems.some((q) => ws.startsWith(q) || q.startsWith(ws))
    out.push(
      hit ? (
        <mark
          key={`m${start}`}
          className="rounded-sm bg-accent/30 px-0.5 text-fg"
        >
          {word}
        </mark>
      ) : (
        <span key={`w${start}`}>{word}</span>
      ),
    )
    cursor = start + word.length
  }
  if (cursor < text.length) out.push(<span key={`s${cursor}`}>{text.slice(cursor)}</span>)
  return out
}

function StatusChip({ status }: { status: string }) {
  const tone =
    status === 'ready'
      ? 'text-accent'
      : status === 'error'
        ? 'text-danger'
        : 'text-muted'
  return <span className={cn('chip', tone)}>{status}</span>
}
