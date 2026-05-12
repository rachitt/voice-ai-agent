import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  Download,
  Phone,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  RefreshCw,
} from 'lucide-react'
import { calls, type CallDetail, type CallListItem } from '@/lib/api'
import { cn } from '@/lib/cn'

const PAGE_SIZE = 50

export function CallsPage() {
  const [items, setItems] = useState<CallListItem[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [recordingOnly, setRecordingOnly] = useState(false)

  const load = useCallback(
    async (reset: boolean) => {
      setLoading(true)
      setErr(null)
      try {
        const opts: { limit: number; cursor?: string; has_recording?: boolean } = {
          limit: PAGE_SIZE,
        }
        if (!reset && cursor) opts.cursor = cursor
        if (recordingOnly) opts.has_recording = true
        const page = await calls.list(opts)
        setItems((prev) => (reset ? page.items : [...prev, ...page.items]))
        setCursor(page.next_cursor)
        setHasMore(Boolean(page.next_cursor))
      } catch (e) {
        setErr(String(e))
      } finally {
        setLoading(false)
      }
    },
    [cursor, recordingOnly],
  )

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- filter change resets list state + triggers fetch
    setItems([])
    setCursor(null)
    setHasMore(false)
    void load(true)
    // intentionally not depending on `load` to avoid double-fire on cursor change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordingOnly])

  return (
    <div className="flex h-full min-h-0 gap-4" data-testid="calls-root">
      <section className="panel flex min-h-0 w-[420px] shrink-0 flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <PhoneCall className="h-4 w-4 text-muted" />
            <h2 className="text-sm font-medium">Calls</h2>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              data-testid="filter-recording"
              data-active={recordingOnly ? '1' : '0'}
              onClick={() => setRecordingOnly((v) => !v)}
              className={cn(
                'rounded-[6px] border px-2 py-1 text-[11px] transition-colors',
                recordingOnly
                  ? 'border-accent bg-accent-soft text-fg'
                  : 'border-border bg-panel-2 text-muted hover:text-fg',
              )}
            >
              w/ recording
            </button>
            <button
              onClick={() => void load(true)}
              className="grid h-7 w-7 place-items-center rounded-[6px] border border-border bg-panel-2 text-muted hover:text-fg"
              title="Refresh"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            </button>
          </div>
        </header>

        {err && (
          <div className="border-b border-border bg-danger/10 px-4 py-2 text-xs text-danger">
            {err}
          </div>
        )}

        <ul className="min-h-0 flex-1 overflow-auto" data-testid="calls-list">
          {items.length === 0 && !loading && (
            <li className="px-4 py-8 text-center text-sm text-muted">
              No calls yet.
            </li>
          )}
          {items.map((c) => (
            <CallRow
              key={c.id}
              call={c}
              active={c.id === selectedId}
              onSelect={() => setSelectedId(c.id)}
            />
          ))}
          {hasMore && (
            <li className="px-4 py-3">
              <button
                data-testid="load-more"
                onClick={() => void load(false)}
                disabled={loading}
                className="w-full rounded-[8px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg disabled:opacity-40"
              >
                {loading ? 'Loading…' : 'Load more'}
                <ChevronDown className="ml-1 inline h-3 w-3" />
              </button>
            </li>
          )}
        </ul>
      </section>

      <section className="panel flex min-h-0 flex-1 flex-col">
        {selectedId ? (
          <CallDetailPanel id={selectedId} />
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-muted">
            Select a call to view transcript + recording.
          </div>
        )}
      </section>
    </div>
  )
}

function CallRow({
  call,
  active,
  onSelect,
}: {
  call: CallListItem
  active: boolean
  onSelect: () => void
}) {
  const DirIcon =
    call.direction === 'inbound'
      ? PhoneIncoming
      : call.direction === 'outbound'
        ? PhoneOutgoing
        : Phone
  const counterparty = call.from_number || call.to_number || '—'
  return (
    <li>
      <button
        data-testid={`call-row-${call.id}`}
        data-active={active ? '1' : '0'}
        onClick={onSelect}
        className={cn(
          'flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left transition-colors',
          active ? 'bg-accent-soft' : 'hover:bg-panel-2',
        )}
      >
        <DirIcon className="h-3.5 w-3.5 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{counterparty}</span>
            <StatusChip status={call.status} />
            {call.has_recording && (
              <span className="chip text-[10px] uppercase">rec</span>
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
            <span>{relTime(call.created_at)}</span>
            <span>{fmtDuration(call.duration_ms)}</span>
          </div>
        </div>
      </button>
    </li>
  )
}

function StatusChip({ status }: { status: string }) {
  const tone =
    status === 'completed'
      ? 'text-accent'
      : status === 'failed'
        ? 'text-danger'
        : 'text-muted'
  return <span className={cn('chip text-[10px] uppercase', tone)}>{status}</span>
}

function CallDetailPanel({ id }: { id: string }) {
  const [detail, setDetail] = useState<CallDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [audioErr, setAudioErr] = useState<string | null>(null)
  const [audioPending, setAudioPending] = useState(false)
  const blobRef = useRef<string | null>(null)

  useEffect(() => {
    let cancelled = false
    // eslint-disable-next-line react-hooks/set-state-in-effect -- id change resets detail panel state before fetching new call
    setDetail(null)
    setErr(null)
    setAudioUrl(null)
    setAudioErr(null)
    setAudioPending(false)
    if (blobRef.current) {
      URL.revokeObjectURL(blobRef.current)
      blobRef.current = null
    }

    calls
      .get(id)
      .then((d) => {
        if (cancelled) return
        setDetail(d)
        if (d.recording_s3_key || d.has_recording) {
          // Prefer a short-lived presigned URL (no streaming through the API
          // process). Fall back to bearer-auth blob fetch when presign is
          // unavailable (dev w/o MinIO, etc.).
          calls
            .recordingUrl(id)
            .then((res) => {
              if (cancelled) return
              if (res.url) {
                setAudioUrl(res.url)
                return
              }
              return calls.recordingBlob(id).then((blob) => {
                if (cancelled) return
                const url = URL.createObjectURL(blob)
                blobRef.current = url
                setAudioUrl(url)
              })
            })
            .catch((e) => {
              if (cancelled) return
              const msg = String(e)
              // 404 with `has_recording=true` listing-side = call is logged
              // but the WAV hasn't landed in object storage yet (post-call
              // upload is async). Surface as "still uploading" so users
              // don't see an error for the normal race.
              if (msg.includes('404') && d.has_recording && !d.recording_s3_key) {
                setAudioPending(true)
                return
              }
              calls
                .recordingBlob(id)
                .then((blob) => {
                  if (cancelled) return
                  const url = URL.createObjectURL(blob)
                  blobRef.current = url
                  setAudioUrl(url)
                })
                .catch((fallbackErr) => {
                  if (cancelled) return
                  const fbMsg = String(fallbackErr)
                  if (fbMsg.includes('404')) {
                    setAudioPending(true)
                  } else {
                    setAudioErr(`${e}; fallback: ${fallbackErr}`)
                  }
                })
            })
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e))
      })

    return () => {
      cancelled = true
      if (blobRef.current) {
        URL.revokeObjectURL(blobRef.current)
        blobRef.current = null
      }
    }
  }, [id])

  const lines = useMemo(() => {
    if (!detail?.transcript) return []
    return detail.transcript.map((t, i) => ({
      id: i,
      who: t.role ?? t.who ?? 'agent',
      text: t.text ?? '',
    }))
  }, [detail])

  if (err)
    return (
      <div className="p-6 text-sm text-danger" data-testid="detail-err">
        {err}
      </div>
    )
  if (!detail) return <div className="p-6 text-sm text-muted">Loading…</div>

  const counterparty = detail.from_number || detail.to_number || '—'
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid={`call-detail-${id}`}>
      <header className="flex items-center justify-between border-b border-border px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="truncate text-sm font-medium">{counterparty}</h3>
            <StatusChip status={detail.status} />
          </div>
          <div className="mt-0.5 flex items-center gap-3 text-[11px] text-muted">
            <span>{detail.direction}</span>
            <span>{relTime(detail.created_at)}</span>
            <span>{fmtDuration(detail.duration_ms)}</span>
            <code className="font-mono text-[10px]">{detail.id}</code>
          </div>
        </div>
        {audioUrl && (
          <a
            data-testid="download-recording"
            href={audioUrl}
            download={`${detail.id}.wav`}
            className="flex items-center gap-1.5 rounded-[6px] border border-border bg-panel-2 px-3 py-1.5 text-xs text-muted hover:text-fg"
          >
            <Download className="h-3.5 w-3.5" /> WAV
          </a>
        )}
      </header>

      {(detail.has_recording || audioUrl || audioErr || audioPending) && (
        <div className="border-b border-border bg-panel-2 px-5 py-3">
          {audioPending ? (
            <div className="text-[11px] text-muted" data-testid="audio-pending">
              recording still uploading — check back in a moment.
            </div>
          ) : audioErr ? (
            <div className="text-[11px] text-danger" data-testid="audio-err">
              recording error: {audioErr}
            </div>
          ) : audioUrl ? (
            <audio
              data-testid="audio"
              controls
              src={audioUrl}
              className="w-full"
              preload="metadata"
            />
          ) : (
            <div className="text-[11px] text-muted">loading recording…</div>
          )}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
        <h4 className="mb-2 text-[11px] uppercase tracking-wider text-muted">
          Transcript
        </h4>
        {lines.length === 0 ? (
          <div className="text-sm text-muted">No transcript captured.</div>
        ) : (
          <ul className="space-y-2" data-testid="transcript">
            {lines.map((l) => (
              <li
                key={l.id}
                className={cn(
                  'rounded-[8px] border px-3 py-2 text-sm',
                  l.who === 'user' || l.who === 'caller'
                    ? 'border-border bg-panel-2 text-fg'
                    : 'border-accent-dim/30 bg-accent-soft text-fg',
                )}
              >
                <div className="mb-0.5 text-[10px] uppercase tracking-wider text-muted">
                  {l.who}
                </div>
                <div>{l.text}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function fmtDuration(ms: number | null): string {
  if (!ms) return '—'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const r = s % 60
  return m > 0 ? `${m}m ${r}s` : `${s}s`
}
