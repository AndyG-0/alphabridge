import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import SpendingCard from './SpendingCard'

const actuals = {
  measured_monthly_avg: 1660,
  plan_monthly: 1500,
  difference: 160,
  difference_pct: 0.1,
  months_used: ['2026-08', '2026-09'],
  by_category_monthly_avg: { housing: 1500 },
  uncategorized_count: 1,
  lifestyle_creep: { flag: true, reason: 'up 12% vs baseline', recent_avg: 1, baseline_avg: 1, change: 0.12 },
  note: 'n',
}

describe('SpendingCard', () => {
  it('shows measured vs plan, the creep flag, and requires a click to apply to plan', async () => {
    let applied = 0
    server.use(
      http.get('*/api/spending/actuals', () => HttpResponse.json(actuals)),
      http.get('*/api/spending/transactions', () =>
        HttpResponse.json({
          categories: ['food'],
          transactions: [{ id: 3, date: '2026-09-06', description: 'MYSTERY', amount: -40, category: '', suggested_category: 'food' }],
        }),
      ),
      http.post('*/api/spending/apply-to-plan', () => {
        applied += 1
        return HttpResponse.json({})
      }),
    )
    render(<SpendingCard />)
    expect(await screen.findByText(/Lifestyle creep/)).toBeInTheDocument()
    expect(screen.getByText(/1 uncategorized/)).toBeInTheDocument()
    expect(applied).toBe(0)
    await userEvent.click(screen.getByRole('button', { name: 'Use measured spend in plan' }))
    expect(applied).toBe(1)
  })
})
