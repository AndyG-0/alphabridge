import { ResponsiveContainer, Sankey, Tooltip } from 'recharts'
import type { CashFlow } from '../../api/client'
import { usd } from '../ui'
import ChartFrame, { isNum, tooltipStyle } from './ChartFrame'

const COLORS = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)', 'var(--viz-axis)']

interface NodeProps {
  x: number
  y: number
  width: number
  height: number
  index: number
  payload: { name: string; value: number }
}
function Node({ x, y, width, height, index, payload }: NodeProps) {
  const right = index !== 0
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={2} fill={COLORS[index % COLORS.length]} />
      <text x={right ? x + width + 6 : x - 6} y={y + height / 2} dy="0.35em" textAnchor={right ? 'start' : 'end'} fontSize={11} fill="var(--foreground)">
        {payload.name} {usd(payload.value)}
      </text>
    </g>
  )
}

/** This year's gross income split into taxes, spending, debt payments, savings and leftover. */
export default function CashFlowSankey({ data, loading, error }: { data?: CashFlow | null; loading?: boolean; error?: unknown }) {
  const idx = (n: string) => (data ? data.nodes.indexOf(n) : -1)
  const graph = data && {
    nodes: data.nodes.map((name) => ({ name })),
    links: data.links.map((l) => ({ source: idx(l.source), target: idx(l.target), value: l.value })),
  }
  return (
    <ChartFrame
      title="Where this year's income goes"
      loading={loading}
      error={error}
      empty={!!data && (data.links.length === 0 || data.gross_income <= 0)}
      invalid={!!data && data.links.some((l) => !isNum(l.value))}
      height={240}
      table={{ caption: 'Income allocation', headers: ['To', 'Annual amount'], rows: (data?.links ?? []).map((l) => [l.target, usd(l.value)]) }}
    >
      {graph ? (
        <ResponsiveContainer>
          <Sankey
            data={graph}
            node={<Node x={0} y={0} width={0} height={0} index={0} payload={{ name: '', value: 0 }} />}
            nodePadding={24}
            nodeWidth={10}
            margin={{ left: 80, right: 150, top: 8, bottom: 8 }}
            link={{ stroke: 'var(--viz-axis)', strokeOpacity: 0.25 }}
          >
            <Tooltip contentStyle={tooltipStyle} formatter={(v) => usd(Number(v))} />
          </Sankey>
        </ResponsiveContainer>
      ) : null}
    </ChartFrame>
  )
}
