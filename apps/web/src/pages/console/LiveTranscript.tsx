import { useEffect, useRef, useState } from 'react'
import { Headphones } from 'lucide-react'
import { api, getApiBase, getApiKey } from '@/lib/api'
import { SEED_TRANSCRIPT, type TranscriptLine } from './fixtures'
import { cn } from '@/lib/cn'

const LS_CALL_ID = 'voice2.watch_call_id'

export function LiveTranscript() {
  const [callId, setCallId] = useState<string>(() => localStorage.getItem(LS_CALL_ID) ?? '')
  const [lines, setLines] = useState<TranscriptLine[]>([])
  const [live, setLive] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    esRef.current?.close()
    esRef.current = null
    setLines([])
    setLive(false)
    setErr(null)
    if (!callId) return

    const key = getApiKey()
    if (!key) {
      setErr('Set API key on the Web Call page first.')
      return
    }

    let cancelled = false
    let counter = 0

    ;(async () => {
      let streamToken: string
      try {
        const { token } = await api.mintStreamToken(callId)
        streamToken = token
      } catch (e) {
        if (cancelled) return
        setErr(`stream auth failed: ${String(e)}`)
        return
      }
      if (cancelled) return

      const url = `${getApiBase()}/v1/calls/${encodeURIComponent(callId)}/stream?token=${encodeURIComponent(streamToken)}`
      const es = new EventSource(url)
      esRef.current = es

      es.addEventListener('ready', () => setLive(true))
      es.onmessage = (e) => {
        try {
          const ev = JSON.parse(e.data) as { type?: string; text?: string }
          if (!ev || !ev.text) return
          if (ev.type === 'user_text' || ev.type === 'agent_text') {
            const idx = ++counter
            const t = secondsToClock(idx)
            setLines((prev) => [
              ...prev,
              {
                id: `live-${idx}`,
                who: ev.type === 'agent_text' ? 'agent' : 'caller',
                text: ev.text ?? '',
                t,
              },
            ])
          }
        } catch {
          // ignore non-JSON
        }
      }
      es.onerror = () => {
        setErr('stream error')
        setLive(false)
      }
    })()

    localStorage.setItem(LS_CALL_ID, callId)
    return () => {
      cancelled = true
      esRef.current?.close()
      esRef.current = null
    }
  }, [callId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [lines.length])

  const display = callId ? lines : SEED_TRANSCRIPT

  return (
    <div className="panel flex flex-col px-5 py-4" data-testid="transcript">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Headphones className="h-4 w-4 text-accent" />
          <div className="text-sm font-medium">Live Transcript</div>
          {callId ? (
            <span
              className="chip"
              data-testid="live-chip"
              data-live={live ? '1' : '0'}
            >
              {live ? 'live · ' : 'connecting · '}
              {callId.slice(0, 10)}…
            </span>
          ) : (
            <span className="chip" data-testid="demo-chip">
              demo data
            </span>
          )}
        </div>
        <input
          data-testid="watch-call-input"
          value={callId}
          onChange={(e) => setCallId(e.target.value.trim())}
          placeholder="watch call_id"
          className="w-[160px] rounded-[6px] border border-border bg-panel-2 px-2 py-1 text-[11px]"
        />
      </div>

      {err && (
        <div className="mb-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[11px] text-red-300">
          {err}
        </div>
      )}

      <Waveform live={live} />

      <div ref={scrollRef} className="mt-3 flex max-h-[240px] flex-col gap-2 overflow-auto pr-1">
        {display.length === 0 ? (
          <div className="text-xs text-muted">Waiting for first turn…</div>
        ) : (
          display.map((l) => <Bubble key={l.id} line={l} />)
        )}
      </div>
    </div>
  )
}

function secondsToClock(i: number): string {
  const s = i * 2
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function Waveform({ live }: { live: boolean }) {
  const bars = Array.from({ length: 48 }, (_, i) => i)
  return (
    <div className="flex h-10 items-center gap-0.5 rounded-[8px] border border-border bg-panel-2 px-2">
      {bars.map((i) => {
        const h = 20 + Math.abs(Math.sin(i * 0.5)) * 70
        return (
          <span
            key={i}
            className={cn('w-[2.5px] rounded-full', live ? 'bg-accent' : 'bg-accent/40')}
            style={{ height: `${h}%`, opacity: 0.35 + (i / bars.length) * 0.65 }}
          />
        )
      })}
    </div>
  )
}

function Bubble({ line }: { line: TranscriptLine }) {
  const isAgent = line.who === 'agent'
  return (
    <div
      data-testid="bubble"
      data-who={line.who}
      className={cn('flex items-start gap-2', isAgent ? '' : 'flex-row-reverse')}
    >
      <div
        className={cn(
          'grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-medium',
          isAgent ? 'bg-accent text-bg' : 'bg-panel-2 text-muted border border-border',
        )}
      >
        {isAgent ? 'AI' : 'SH'}
      </div>
      <div
        className={cn(
          'max-w-[78%] rounded-[10px] px-3 py-1.5 text-[12px] leading-relaxed',
          isAgent
            ? 'bg-accent-soft text-fg border border-[color:var(--color-accent-dim)]'
            : 'bg-panel-2 text-fg border border-border',
        )}
      >
        {line.text}
        <span className="ml-2 align-middle text-[10px] text-muted">{line.t}</span>
      </div>
    </div>
  )
}
