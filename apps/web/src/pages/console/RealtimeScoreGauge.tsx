import { RadialBar, RadialBarChart, ResponsiveContainer, PolarAngleAxis } from 'recharts'
import { SCORE_BREAKDOWN } from './fixtures'

export function RealtimeScoreGauge() {
  const score = 92
  const data = [{ name: 'score', value: score, fill: '#22e07a' }]

  return (
    <div className="panel px-5 py-4">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">Realtime Score</div>
        <span className="chip">live · 5s window</span>
      </div>

      <div className="mt-2 flex items-center gap-4">
        <div className="relative h-[120px] w-[120px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <RadialBarChart
              innerRadius="76%"
              outerRadius="100%"
              data={data}
              startAngle={90}
              endAngle={-270}
            >
              <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
              <RadialBar background={{ fill: '#1e2624' }} dataKey="value" cornerRadius={8} />
            </RadialBarChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <div className="text-center">
              <div className="text-2xl font-medium leading-none">{score}</div>
              <div className="mt-1 text-[10px] uppercase tracking-wider text-muted">score</div>
            </div>
          </div>
        </div>

        <ul className="grid flex-1 grid-cols-1 gap-1.5">
          {SCORE_BREAKDOWN.map((b) => (
            <li key={b.key} className="flex items-center justify-between text-[11px]">
              <span className="text-muted">{b.label}</span>
              <span className="font-mono text-fg">{b.value}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
