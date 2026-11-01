import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { ScenarioCompare as Compare } from '../../api/client'
import ChartFrame, { axisTick, gridStroke, isNum, tooltipStyle } from './ChartFrame'

const pct = (x: number) => `${(x * 100).toFixed(0)}%`

/** Success rate per scenario against the baseline (dashed line). */
export default function ScenarioCompare({ data, loading, error }: { data?: Compare | null; loading?: boolean; error?: unknown }) {
  const rows = data
    ? [
        { name: 'Baseline', rate: data.base.success_rate, base: true },
        ...data.scenarios.map((s) => ({ name: s.name, rate: s.metrics.success_rate, base: false })),
      ]
    : []
  return (
    <ChartFrame
      title="Chance of success by scenario"
      loading={loading}
      error={error}
      empty={!!data && rows.length < 2}
      invalid={rows.some((r) => !isNum(r.rate))}
      legend={[
        { label: 'Baseline', color: 'var(--viz-1)' },
        { label: 'Scenario', color: 'var(--viz-2)' },
      ]}
      table={{ caption: 'Success rate by scenario', headers: ['Scenario', 'Success'], rows: rows.map((r) => [r.name, pct(r.rate)]) }}
    >
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={gridStroke} />
          <XAxis dataKey="name" tick={axisTick} stroke={gridStroke} tickLine={false} interval={0} />
          <YAxis domain={[0, 1]} tickFormatter={pct} tick={axisTick} width={40} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => [pct(Number(v)), 'Success']} />
          {data && <ReferenceLine y={data.base.success_rate} stroke="var(--viz-axis)" strokeDasharray="4 3" />}
          <Bar dataKey="rate" radius={[4, 4, 0, 0]} isAnimationActive={false}>
            {rows.map((r) => (
              <Cell key={r.name} fill={r.base ? 'var(--viz-1)' : 'var(--viz-2)'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
