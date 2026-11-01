import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import type { BracketFill, CashFlow, FirePathPoint, ScenarioCompare as Compare, WithdrawalYear } from '../../api/client'
import BracketAcaVisualizer from './BracketAcaVisualizer'
import CashFlowSankey from './CashFlowSankey'
import ChartFrame from './ChartFrame'
import FanChart from './FanChart'
import ScenarioCompare from './ScenarioCompare'
import StackedYears from './StackedYears'
import WithdrawalStack from './WithdrawalStack'

beforeAll(() => {
  // recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

const pt = (year: number, value: number): FirePathPoint => ({
  year,
  ages: { SELF: 40 },
  value,
  p10: value / 2,
  p25: value * 0.8,
  p75: value * 1.2,
  p90: value * 2,
})
const wy = (year: number): WithdrawalYear => ({
  year,
  age: 60,
  draw_taxable: 1000,
  draw_pretax: 2000,
  draw_roth: 0,
  social_security: 0,
  magi: 3000,
  tax: 100,
  marginal_rate: 0.1,
  aca_premium: 0,
  aca_over_cliff: false,
  shortfall: 0,
  balances: { taxable: 0, pretax: 0, roth: 0 },
})
const bf: BracketFill = {
  year: 2026,
  status: 'SINGLE',
  magi: 60000,
  standard_deduction: 16100,
  taxable_income: 43900,
  tax: 5000,
  marginal_rate: 0.22,
  bands: [
    { from: 0, to: 12400, rate: 0.1, filled: 12400 },
    { from: 12400, to: 50400, rate: 0.12, filled: 31500 },
    { from: 50400, to: null, rate: 0.22, filled: 0 },
  ],
  source_url: 'https://example.gov',
  retrieved_on: '2026-10-31',
}
const flow: CashFlow = {
  year: 2026,
  gross_income: 100,
  effective_tax_rate: 0.2,
  nodes: ['Income', 'Taxes', 'Spending'],
  links: [
    { source: 'Income', target: 'Taxes', value: 20 },
    { source: 'Income', target: 'Spending', value: 80 },
  ],
  shortfall: 0,
  note: '',
}

describe('ChartFrame states', () => {
  it('shows loading, error, empty and invalid messages instead of a chart', () => {
    const { rerender } = render(
      <ChartFrame title="T" loading>
        x
      </ChartFrame>,
    )
    expect(screen.getByText(/Loading chart/)).toBeInTheDocument()
    rerender(
      <ChartFrame title="T" error={new Error('boom')}>
        x
      </ChartFrame>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    rerender(
      <ChartFrame title="T" empty>
        x
      </ChartFrame>,
    )
    expect(screen.getByText(/Nothing to chart/)).toBeInTheDocument()
    rerender(
      <ChartFrame title="T" invalid>
        x
      </ChartFrame>,
    )
    expect(screen.getByText(/not valid numbers/)).toBeInTheDocument()
  })
  it('offers a legend for 2+ series and a table view', () => {
    render(
      <ChartFrame
        title="T"
        legend={[
          { label: 'A', color: 'red' },
          { label: 'B', color: 'blue' },
        ]}
        table={{ caption: 'c', headers: ['H'], rows: [[1]] }}
      >
        <span />
      </ChartFrame>,
    )
    expect(screen.getByRole('list', { name: 'Legend' })).toBeInTheDocument()
    expect(screen.getByText('View as table')).toBeInTheDocument()
  })
})

describe('charts', () => {
  it('FanChart: data renders a table view of all percentiles; empty and NaN are guarded', () => {
    const { rerender } = render(<FanChart path={[pt(2030, 100000), pt(2031, 120000)]} />)
    expect(screen.getByText('2031')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Legend' })).toBeInTheDocument()
    rerender(<FanChart path={[]} />)
    expect(screen.getByText(/Nothing to chart/)).toBeInTheDocument()
    rerender(<FanChart path={[{ ...pt(2030, 1), p90: NaN }]} />)
    expect(screen.getByText(/not valid numbers/)).toBeInTheDocument()
    rerender(<FanChart loading />)
    expect(screen.getByText(/Loading chart/)).toBeInTheDocument()
  })

  it('WithdrawalStack / StackedYears: hides sources that are always zero and guards NaN', () => {
    const { rerender } = render(<WithdrawalStack years={[wy(2040), wy(2041)]} />)
    expect(screen.getAllByText('Pre-tax (401k/IRA)').length).toBeGreaterThan(0)
    expect(screen.queryByText('Roth')).not.toBeInTheDocument()
    rerender(<WithdrawalStack years={[]} />)
    expect(screen.getByText(/Nothing to chart/)).toBeInTheDocument()
    rerender(<StackedYears title="x" series={[{ key: 'a', label: 'A' }]} rows={[{ age: 1, a: NaN }]} />)
    expect(screen.getByText(/not valid numbers/)).toBeInTheDocument()
  })

  it('BracketAcaVisualizer: shows bracket and ACA tables, empty when no data', () => {
    const aca = {
      rules_year: 2026,
      enhanced: false,
      fpl: 15000,
      cliff_magi: 62600,
      points: [
        { fpl_ratio: 1, magi: 15000, net_premium: 500, credit: 5000, medicaid: false },
        { fpl_ratio: 4, magi: 60000, net_premium: 9000, credit: 1000, medicaid: false },
      ],
    }
    const { rerender } = render(<BracketAcaVisualizer brackets={bf} aca={aca} />)
    expect(screen.getByText(/Federal brackets filled at \$60,000/)).toBeInTheDocument()
    expect(screen.getByText(/ACA net premium by income \(2026 rules\)/)).toBeInTheDocument()
    rerender(<BracketAcaVisualizer brackets={null} aca={null} />)
    expect(screen.getAllByText(/Nothing to chart/)).toHaveLength(2)
  })

  it('CashFlowSankey: tabulates flows; empty when no income', () => {
    const { rerender } = render(<CashFlowSankey data={flow} />)
    expect(screen.getByText('Spending')).toBeInTheDocument()
    rerender(<CashFlowSankey data={{ ...flow, gross_income: 0, links: [] }} />)
    expect(screen.getByText(/Nothing to chart/)).toBeInTheDocument()
    rerender(<CashFlowSankey data={{ ...flow, links: [{ source: 'Income', target: 'Taxes', value: NaN }] }} />)
    expect(screen.getByText(/not valid numbers/)).toBeInTheDocument()
  })

  it('ScenarioCompare: baseline plus scenarios; needs at least one scenario', () => {
    const m = { success_rate: 0.8, bridge_success_rate: 1, median_final_real: 1, retire_age: 55, monthly_spend: 1 }
    const data: Compare = { base: m, scenarios: [{ name: 'Retire later', kind: 'preset', metrics: { ...m, success_rate: 0.9 }, vs_base: {} }] }
    const { rerender } = render(<ScenarioCompare data={data} />)
    expect(screen.getByText('Retire later')).toBeInTheDocument()
    rerender(<ScenarioCompare data={{ base: m, scenarios: [] }} />)
    expect(screen.getByText(/Nothing to chart/)).toBeInTheDocument()
  })
})
