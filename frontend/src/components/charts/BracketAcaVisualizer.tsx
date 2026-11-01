import { Area, AreaChart, Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { AcaSchedule, BracketFill } from '../../api/client'
import { usd } from '../ui'
import ChartFrame, { axisTick, gridStroke, isNum, money, tooltipStyle } from './ChartFrame'

/** How much of each federal bracket a year's income fills, and where it sits on the ACA premium schedule (cliff marked). */
export default function BracketAcaVisualizer({
  brackets,
  aca,
  loading,
  error,
}: {
  brackets?: BracketFill | null
  aca?: AcaSchedule | null
  loading?: boolean
  error?: unknown
}) {
  const bands = (brackets?.bands ?? []).map((b) => ({
    label: `${Math.round(b.rate * 100)}%`,
    filled: b.filled,
    room: b.to === null ? 0 : Math.max(b.to - b.from - b.filled, 0),
  }))
  const pts = (aca?.points ?? []).map((p) => ({ magi: p.magi, net: p.net_premium }))
  const invalid = bands.some((b) => !isNum(b.filled) || !isNum(b.room)) || pts.some((p) => !isNum(p.magi) || !isNum(p.net))
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ChartFrame
        showTitle
        title={brackets ? `Federal brackets filled at ${usd(brackets.magi)} income` : 'Federal brackets'}
        loading={loading}
        error={error}
        empty={!brackets || bands.length === 0}
        invalid={invalid}
        legend={[
          { label: 'Income in this bracket', color: 'var(--viz-1)' },
          { label: 'Room left in bracket', color: 'var(--viz-grid)' },
        ]}
        table={{
          caption: 'Income filling each bracket',
          headers: ['Bracket', 'Filled', 'Room left'],
          rows: bands.map((b) => [b.label, usd(b.filled), usd(b.room)]),
        }}
      >
        <ResponsiveContainer>
          <BarChart data={bands} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={gridStroke} />
            <XAxis dataKey="label" tick={axisTick} stroke={gridStroke} tickLine={false} />
            <YAxis tickFormatter={money} tick={axisTick} width={52} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [usd(Number(v)), String(n)]} />
            <Bar dataKey="filled" name="Filled" stackId="a" fill="var(--viz-1)" stroke="var(--viz-surface)" isAnimationActive={false} />
            <Bar dataKey="room" name="Room left" stackId="a" fill="var(--viz-grid)" stroke="var(--viz-surface)" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </ChartFrame>
      <ChartFrame
        showTitle
        title={aca ? `ACA net premium by income (${aca.rules_year} rules)` : 'ACA premium schedule'}
        loading={loading}
        error={error}
        empty={!aca || pts.length === 0}
        invalid={invalid}
        table={{ caption: 'ACA net annual premium by MAGI', headers: ['MAGI', 'Net premium / yr'], rows: pts.map((p) => [usd(p.magi), usd(p.net)]) }}
      >
        <ResponsiveContainer>
          <AreaChart data={pts} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={gridStroke} />
            <XAxis dataKey="magi" type="number" domain={['dataMin', 'dataMax']} tickFormatter={money} tick={axisTick} stroke={gridStroke} tickLine={false} />
            <YAxis tickFormatter={money} tick={axisTick} width={52} axisLine={false} tickLine={false} />
            <Tooltip contentStyle={tooltipStyle} labelFormatter={(v) => `MAGI ${usd(Number(v))}`} formatter={(v) => [usd(Number(v)), 'Net premium / yr']} />
            <Area dataKey="net" type="stepAfter" stroke="var(--viz-2)" strokeWidth={2} fill="var(--viz-2)" fillOpacity={0.15} isAnimationActive={false} />
            {aca?.cliff_magi != null && (
              <ReferenceLine
                x={aca.cliff_magi}
                stroke="var(--viz-axis)"
                strokeDasharray="4 3"
                label={{ value: 'Cliff', fill: 'var(--viz-axis)', fontSize: 11, position: 'insideTopLeft' }}
              />
            )}
            {brackets && (
              <ReferenceLine
                x={brackets.magi}
                stroke="var(--viz-1)"
                strokeWidth={2}
                label={{ value: 'You', fill: 'var(--viz-axis)', fontSize: 11, position: 'insideTopRight' }}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </ChartFrame>
    </div>
  )
}
