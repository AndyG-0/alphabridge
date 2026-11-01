import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import RebalanceCard from './RebalanceCard'

const loc = { marginal_rate: 0.24, note: 'Placement goals.', suggestions: [] }

describe('RebalanceCard', () => {
  it('prompts for a target when none is set', async () => {
    server.use(http.get('*/api/rebalance', () => HttpResponse.json({ has_target: false, notes: ['Set a target allocation first.'], asset_location: loc })))
    render(<RebalanceCard />)
    expect(await screen.findByText(/Set a target allocation first/)).toBeInTheDocument()
    expect(screen.getByText('Set target allocation')).toBeInTheDocument()
  })

  it('shows drift, trades and the tax estimate', async () => {
    server.use(
      http.get('*/api/rebalance', () =>
        HttpResponse.json({
          has_target: true,
          notes: [],
          drift: {
            total: 10000,
            total_drift: 0.2,
            threshold: 0.05,
            breached: true,
            rows: [
              { asset_class: 'US_EQUITY', current: 0.8, target: 0.6, drift: 0.2, dollars: -2000, breach: true },
              { asset_class: 'BOND', current: 0.2, target: 0.4, drift: -0.2, dollars: 2000, breach: true },
            ],
          },
          trades: [
            {
              account_id: 1,
              account: 'Brokerage',
              tax_bucket: 'TAXABLE_BROKERAGE',
              action: 'SELL',
              symbol: 'VTI',
              asset_class: 'US_EQUITY',
              amount: 2000,
              realized_gain: 1000,
            },
            {
              account_id: 1,
              account: 'Brokerage',
              tax_bucket: 'TAXABLE_BROKERAGE',
              action: 'BUY',
              symbol: 'BND',
              asset_class: 'BOND',
              amount: 2000,
              realized_gain: 0,
            },
          ],
          unresolved: { sell: {}, buy: {} },
          realized_gains: 1000,
          est_tax: 150,
          after: { total_drift: 0 },
          asset_location: loc,
        }),
      ),
    )
    render(<RebalanceCard />)
    expect(await screen.findByText(/20.0% of the portfolio needs to move/)).toBeInTheDocument()
    expect(screen.getByText(/est. federal tax \$150/)).toBeInTheDocument()
    expect(screen.getByText('Edit target allocation')).toBeInTheDocument()
  })
})
