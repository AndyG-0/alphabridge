import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import PerformanceCard from './PerformanceCard'

const base = {
  points: 0,
  flow_mode: 'none',
  flows: 0,
  notes: ['Performance needs at least two net-worth snapshots on different days.'],
  returns: null,
  fees: {
    annual_fee: 120,
    weighted_expense_ratio: 0.0012,
    covered_pct: 0.9,
    unknown: ['ZZZZ'],
    rows: [],
    drag: { '10': { cost: 5000, cost_pct: 0.02, years: 10 } },
  },
  income: {
    months: Array.from({ length: 12 }, (_, i) => ({ month: i + 1, amount: i % 3 === 2 ? 100 : 10 })),
    annual_income: 440,
    missing_yield: [],
    assumption: 'Quarterly.',
  },
}

describe('PerformanceCard', () => {
  it('explains missing history and still shows fees and income', async () => {
    server.use(http.get('*/api/performance', () => HttpResponse.json(base)))
    render(<PerformanceCard />)
    expect(await screen.findByText(/at least two net-worth snapshots/)).toBeInTheDocument()
    expect(screen.getByText(/No expense ratio for: ZZZZ/)).toBeInTheDocument()
    expect(screen.getByText(/Over 10 years/)).toBeInTheDocument()
  })

  it('shows TWR, IRR and benchmark excess', async () => {
    server.use(
      http.get('*/api/performance', () =>
        HttpResponse.json({
          ...base,
          points: 3,
          notes: [],
          returns: {
            twr: { total: 0.26, annualized: null, days: 59, periods: [] },
            mwr: 0.31,
            start: '2025-01-01',
            end: '2025-03-01',
            start_value: 1000,
            end_value: 1650,
          },
          benchmarks: { market: { name: 'SPY (US stocks)', return: 0.05, excess: 0.21 }, target: null, approximate: true },
        }),
      ),
    )
    render(<PerformanceCard />)
    expect(await screen.findByText('26.0%')).toBeInTheDocument()
    expect(screen.getByText('31.0%')).toBeInTheDocument()
    expect(screen.getByText(/excess 21.0%/)).toBeInTheDocument()
  })
})
