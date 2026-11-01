import { Area, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid } from 'recharts'
import type { FirePathPoint } from '../../api/client'
import { usd } from '../ui'
import ChartFrame, { axisTick, gridStroke, isNum, money, tooltipStyle } from './ChartFrame'

const BAND_KEYS = ['p10', 'p25', 'value', 'p75', 'p90'] as const

/** Monte Carlo percentile fan: 10-90% and 25-75% bands around the median, all computed server-side. */
export default function FanChart({
  path,
  loading,
  error,
  ageLabel,
}: {
  path?: FirePathPoint[]
  loading?: boolean
  error?: unknown
  ageLabel?: (p: FirePathPoint) => string
}) {
  const invalid = !!path?.some((p) => BAND_KEYS.some((k) => !isNum(p[k])))
  const data = (path ?? []).map((p) => ({ ...p, outer: [p.p10, p.p90], inner: [p.p25, p.p75] }))
  return (
    <ChartFrame
      title="Projected savings range (today's dollars)"
      loading={loading}
      error={error}
      empty={!!path && path.length === 0}
      invalid={invalid}
      legend={[
        { label: 'Median', color: 'var(--viz-1)' },
        { label: 'Middle half of outcomes (25th–75th)', color: 'color-mix(in srgb, var(--viz-1) 35%, transparent)' },
        { label: 'Worst/best 10% excluded (10th–90th)', color: 'color-mix(in srgb, var(--viz-1) 15%, transparent)' },
      ]}
      table={{
        caption: 'Savings percentile by year',
        headers: ['Year', '10th', '25th', 'Median', '75th', '90th'],
        rows: (path ?? []).map((p) => [p.year, usd(p.p10), usd(p.p25), usd(p.value), usd(p.p75), usd(p.p90)]),
      }}
    >
      <ResponsiveContainer>
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={gridStroke} />
          <XAxis dataKey="year" tick={axisTick} stroke={gridStroke} tickLine={false} minTickGap={24} />
          <YAxis tickFormatter={money} tick={axisTick} width={52} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={tooltipStyle}
            labelFormatter={(_, pl) => {
              const row = pl?.[0]?.payload as FirePathPoint | undefined
              return row ? `${row.year}${ageLabel ? ` · ${ageLabel(row)}` : ''}` : ''
            }}
            formatter={(v, name) => {
              const label: Record<string, string> = { outer: '10th–90th', inner: '25th–75th', value: 'Median' }
              return [Array.isArray(v) ? `${usd(Number(v[0]))} – ${usd(Number(v[1]))}` : usd(Number(v)), label[String(name)] ?? String(name)]
            }}
          />
          <Area dataKey="outer" stroke="none" fill="var(--viz-1)" fillOpacity={0.15} isAnimationActive={false} />
          <Area dataKey="inner" stroke="none" fill="var(--viz-1)" fillOpacity={0.3} isAnimationActive={false} />
          <Line
            dataKey="value"
            stroke="var(--viz-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: 'var(--viz-surface)', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
