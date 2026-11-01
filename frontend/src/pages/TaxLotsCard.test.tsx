import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import TaxLotsCard from './TaxLotsCard'

const lot = {
  id: 1,
  account_id: 1,
  symbol: 'QQQ',
  acquired: '2024-01-01',
  shares: 10,
  cost_basis: 5000,
  value: 4000,
  gain: -1000,
  term: 'LONG',
  days_to_long_term: 0,
}

describe('TaxLotsCard', () => {
  it('asks for a lot export when there are none', async () => {
    server.use(http.get('*/api/tax-lots', () => HttpResponse.json({ lots: 0, missing_lots: [], notes: ['Import a lot-level cost-basis export first.'] })))
    render(<TaxLotsCard />)
    expect(await screen.findByText(/Import a lot-level cost-basis export first/)).toBeInTheDocument()
  })

  it('lists harvest candidates and wash-sale blocks', async () => {
    server.use(
      http.get('*/api/tax-lots', () =>
        HttpResponse.json({
          lots: 2,
          missing_lots: ['NVDA'],
          notes: [],
          harvest: {
            candidates: [
              {
                ...lot,
                account: 'Brokerage',
                loss: 1000,
                rate: 0.15,
                est_tax_savings: 150,
                alternatives: ['VGT'],
                identical_to: ['QQQ'],
                wash_conflicts: [],
                avoid_buying_until: '2026-07-16',
              },
            ],
            blocked_by_wash_sale: [
              {
                ...lot,
                id: 2,
                symbol: 'VOO',
                account: 'Brokerage',
                loss: 500,
                rate: 0.15,
                est_tax_savings: 75,
                alternatives: [],
                identical_to: [],
                wash_conflicts: [{ account: 'IRA', symbol: 'IVV', acquired: '2026-06-10', owner: 'SELF' }],
                avoid_buying_until: '',
              },
            ],
            total_loss: 1000,
            total_est_savings: 150,
            note: 'Federal only.',
          },
          gain_harvest: { zero_bracket_top: 48350, headroom: 20000, total_gain: 0, picks: [], note: 'n' },
        }),
      ),
    )
    render(<TaxLotsCard />)
    expect(await screen.findByText(/saves ~\$150 at 15%/)).toBeInTheDocument()
    expect(screen.getByText(/VOO loss \$500 blocked: IVV bought 2026-06-10 in IRA/)).toBeInTheDocument()
    expect(screen.getByText(/No lot data yet for: NVDA/)).toBeInTheDocument()
  })
})
