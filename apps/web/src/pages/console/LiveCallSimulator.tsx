import { Mic, Grid3x3, Volume2, Pause, PhoneOff, Play } from 'lucide-react'

export function LiveCallSimulator() {
  return (
    <div className="panel flex flex-col px-5 py-4">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
          <div className="text-sm font-medium">Live Call Simulator</div>
        </div>
        <button className="text-[11px] text-muted hover:text-fg">Call analysis →</button>
      </div>

      <div className="flex flex-1 items-center justify-center">
        <PhoneMockup />
      </div>

      <div className="mt-4 flex items-center justify-between gap-2 rounded-[10px] border border-border bg-panel-2 px-3 py-2">
        <span className="text-[11px] text-muted">All callbacks operational</span>
        <div className="flex gap-2">
          <button className="rounded-[8px] border border-border bg-bg px-3 py-1.5 text-[11px] text-muted hover:text-fg">
            Test with your number
          </button>
          <button className="inline-flex items-center gap-1.5 rounded-[8px] bg-accent px-3 py-1.5 text-[11px] font-medium text-bg hover:bg-[#3aef8d]">
            <Play className="h-3 w-3" /> Launch test
          </button>
        </div>
      </div>
    </div>
  )
}

function PhoneMockup() {
  return (
    <div className="relative h-[330px] w-[180px] rounded-[28px] border border-border-strong bg-gradient-to-b from-[#171c1a] to-[#0d1110] p-2 shadow-[0_30px_60px_-30px_rgba(34,224,122,0.25),inset_0_0_0_1px_rgba(255,255,255,0.04)]">
      <div className="absolute left-1/2 top-2 z-10 h-4 w-16 -translate-x-1/2 rounded-full bg-bg" />
      <div className="flex h-full flex-col items-center justify-between rounded-[22px] bg-bg px-3 pb-3 pt-7">
        <div className="text-[10px] text-muted">+1 (415) 555-0188</div>

        <div className="flex flex-col items-center gap-2">
          <div className="grid h-16 w-16 place-items-center rounded-full bg-gradient-to-br from-accent to-accent-dim text-lg font-medium text-bg">
            SH
          </div>
          <div className="text-center">
            <div className="text-[13px] font-medium">Sarah H.</div>
            <div className="text-[10px] text-muted">Acme Inc · Connected · 00:43</div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <CtrlBtn icon={Mic} />
          <CtrlBtn icon={Grid3x3} />
          <CtrlBtn icon={Volume2} />
          <CtrlBtn icon={Pause} />
          <button className="col-span-1 grid h-9 w-9 place-items-center rounded-full bg-danger text-bg">
            <PhoneOff className="h-3.5 w-3.5" />
          </button>
          <CtrlBtn icon={Mic} disabled />
        </div>
      </div>
    </div>
  )
}

function CtrlBtn({ icon: Icon, disabled }: { icon: React.ComponentType<{ className?: string }>; disabled?: boolean }) {
  return (
    <button
      disabled={disabled}
      className="grid h-9 w-9 place-items-center rounded-full border border-border bg-panel text-muted hover:text-fg disabled:opacity-30"
    >
      <Icon className="h-3.5 w-3.5" />
    </button>
  )
}
