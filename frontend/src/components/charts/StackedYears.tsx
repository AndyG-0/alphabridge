import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usd } from '../ui'
import ChartFrame, { axisTick, gridStroke, isNum, money, tooltipStyle } from './ChartFrame'

export interface StackSeries {
  key: string
  label: string
}
const COLORS = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)']

/** Per-year stacked bars (one series per source). Used for withdrawals by account type and for the Roth conversion ladder. */
export default function StackedYears({
  title,
  rows,
  series,
  xKey = 'age',
  xLabel = 'Age',
  loading,
  error,
}: {
  title: string
  rows?: Record<string, number>[]
  series: StackSeries[]
  xKey?: string
  xLabel?: string
  loading?: boolean
  error?: unknown
}) {
  const invalid = !!rows?.some((r) => series.some((s) => !isNum(r[s.key])))
  const shown = series.filter((s) => rows?.some((r) => r[s.key] > 0))
  const color = (k: string) => COLORS[series.findIndex((s) => s.key === k) % COLORS.length]
  return (
    <ChartFrame
      title={title}
      loading={loading}
      error={error}
      empty={!!rows && (rows.length === 0 || shown.length === 0)}
      invalid={invalid}
      legend={shown.map((s) => ({ label: s.label, color: color(s.key) }))}
      table={{ caption: title, headers: [xLabel, ...shown.map((s) => s.label)], rows: (rows ?? []).map((r) => [r[xKey], ...shown.map((s) => usd(r[s.key]))]) }}
    >
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={gridStroke} />
          <XAxis dataKey={xKey} tick={axisTick} stroke={gridStroke} tickLine={false} minTickGap={12} />
          <YAxis tickFormatter={money} tick={axisTick} width={52} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={tooltipStyle}
            cursor={{ fill: 'var(--accent)', opacity: 0.4 }}
            labelFormatter={(v) => `${xLabel} ${v}`}
            formatter={(v, n) => [usd(Number(v)), String(n)]}
          />
          {shown.map((s) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId="a"
              fill={color(s.key)}
              stroke="var(--viz-surface)"
              strokeWidth={1}
              isAnimationActive={false}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
