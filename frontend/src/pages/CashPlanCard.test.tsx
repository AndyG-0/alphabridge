import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import CashPlanCard from './CashPlanCard'

const plan = {
  signal: 'DCA',
  ladder: {
    instrument: 'TBILL',
    amount: 30000,
    blended_yield: 0.041,
    annual_interest: 1230,
    next_maturity: '2027-01-31',
    rungs: [{ months: 3, amount: 15000, yield: 0.04, matures_on: '2027-01-31', interest_at_maturity: 150 }],
  },
  ladder_available: 30000,
  tax_comparison: { state: 'CA', state_rate: 0.04, state_rate_known: false, mmf_after_tax: 2800, tbill_after_tax: 3000, advantage: 200, winner: 'TBILL' },
  i_bond: {
    annual_purchase_cap: 10000,
    verdict: 'Enter the current I-bond composite rate to compare it with T-bills.',
    min_hold_months: 12,
    early_redemption_penalty: '',
  },
  emergency_fund: { months: 6, essential_monthly: 4000, target: 24000, have_cash: 20000, gap: 4000 },
  bridge_reserve: { years: 2, total: 90000, per_year: [45000, 45000], first_year: 2040, retire_age: 50 },
  total_reserve_target: 114000,
  dca: { amount: 900, tranches: 3, schedule: [{ on: '2026-11-01', amount: 300 }] },
  dca_active: null,
  notes: [],
}

describe('CashPlanCard', () => {
  it('shows reserves, tax comparison, ladder and offers to save a DCA schedule', async () => {
    let saved: unknown = null
    server.use(
      http.get('*/api/planner/cash/plan', () => HttpResponse.json(plan)),
      http.post('*/api/planner/cash/dca', async ({ request }) => {
        saved = await request.json()
        return HttpResponse.json({ amount: 900, tranches: 3, schedule: plan.dca.schedule, notified: [] })
      }),
    )
    render(<CashPlanCard />)
    expect(await screen.findByText(/T-bills ahead by/)).toBeInTheDocument()
    expect(screen.getByText(/\$4,000 short/)).toBeInTheDocument()
    expect(screen.getByText('3 mo')).toBeInTheDocument()
    await userEvent.click(screen.getByText(/Save schedule/))
    expect(saved).toEqual({ amount: 900, tranches: 3 })
  })
})
