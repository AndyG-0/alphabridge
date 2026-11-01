import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import RiskCard from './RiskCard'

const stress = [
  {
    id: 'gfc',
    label: 'Global financial crisis (2008)',
    portfolio_change: -30000,
    portfolio_return: -0.3,
    benchmark: { stocks: -0.37, bonds: 0.2, bills: 0.014 },
    by_class: {},
  },
]

describe('RiskCard', () => {
  it('says so when there are no holdings', async () => {
    server.use(http.get('*/api/portfolio/risk', () => HttpResponse.json({ total: 0, notes: ['No holdings yet.'], stress: [] })))
    render(<RiskCard />)
    expect(await screen.findByText('No holdings yet.')).toBeInTheDocument()
  })

  it('shows metrics, risk shares, correlation and stress rows', async () => {
    server.use(
      http.get('*/api/portfolio/risk', () =>
        HttpResponse.json({
          total: 100000,
          notes: [],
          coverage: { priced_pct: 0.95, unpriced: ['WEIRD'], proxied: ['PLANFUND via BND'], cash_pct: 0.05 },
          risk: {
            days: 300,
            volatility: 0.15,
            max_drawdown: -0.12,
            var_1d: 0.015,
            cvar_1d: 0.02,
            var_1d_dollars: 1500,
            cvar_1d_dollars: 2000,
            confidence: 0.95,
            beta: 0.93,
          },
          contribution: [{ symbol: 'VTI', weight: 0.5, risk_share: 0.7 }],
          correlation: { VTI: { VTI: 1, VGT: 0.9 }, VGT: { VTI: 0.9, VGT: 1 } },
          stress,
        }),
      ),
    )
    render(<RiskCard />)
    expect(await screen.findByText('15.0%')).toBeInTheDocument()
    expect(screen.getByText('0.93')).toBeInTheDocument()
    expect(screen.getByText(/70% of risk · 50% weight/)).toBeInTheDocument()
    expect(screen.getByText(/no history for WEIRD/)).toBeInTheDocument()
    expect(screen.getByText('Global financial crisis (2008)')).toBeInTheDocument()
    expect(screen.getAllByText('0.90').length).toBe(2)
  })
})
