import { useEffect, useRef, useState } from 'react'
import { Headphones } from 'lucide-react'
import { SEED_TRANSCRIPT, STREAM_TRANSCRIPT, type TranscriptLine } from './fixtures'
import { cn } from '@/lib/cn'

export function LiveTranscript() {
  const [lines, setLines] = useState<TranscriptLine[]>(SEED_TRANSCRIPT)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const id = setInterval(() => {
      setLines((prev) => {
        const nextIdx = prev.length - SEED_TRANSCRIPT.length
        const next = STREAM_TRANSCRIPT[nextIdx]
        if (!next) {
          clearInterval(id)
          return prev
        }
        if (prev.some((l) => l.id === next.id)) return prev
        return [...prev, next]
      })
    }, 2200)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [lines.length])

  return (
    <div className="panel flex flex-col px-5 py-4" data-testid="transcript">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Headphones className="h-4 w-4 text-accent" />
          <div className="text-sm font-medium">Live Transcript</div>
          <span className="chip">Caller · Sarah H.</span>
        </div>
        <button className="text-[11px] text-muted hover:text-fg">View full transcript →</button>
      </div>

      <Waveform />

      <div ref={scrollRef} className="mt-3 flex max-h-[240px] flex-col gap-2 overflow-auto pr-1">
        {lines.map((l) => (
          <Bubble key={l.id} line={l} />
        ))}
      </div>
    </div>
  )
}

function Waveform() {
  const bars = Array.from({ length: 48 }, (_, i) => i)
  return (
    <div className="flex h-10 items-center gap-0.5 rounded-[8px] border border-border bg-panel-2 px-2">
      {bars.map((i) => {
        const h = 20 + Math.abs(Math.sin(i * 0.5)) * 70
        return (
          <span
            key={i}
            className="w-[2.5px] rounded-full bg-accent/60"
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
