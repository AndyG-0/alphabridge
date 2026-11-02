import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import SpendingGoalsCard, { windowText } from './SpendingGoalsCard'

const travel = {
  id: 1,
  name: 'Travel',
  category: 'travel',
  annual_amount: 12000,
  start_basis: 'YEARS_AFTER_RETIREMENT',
  start_value: 0,
  end_basis: 'YEARS_AFTER_RETIREMENT',
  end_value: 15,
  owner: 'SELF',
  real_inflation: 0,
  smile_applies: true,
  enabled: true,
  note: '',
  sort_order: 0,
}
const preset = Object.fromEntries(Object.entries(travel).filter(([k]) => !['id', 'owner', 'real_inflation', 'enabled', 'note', 'sort_order'].includes(k)))
const presets = { presets: { travel: preset }, verified: false, notes: '' }

describe('SpendingGoalsCard', () => {
  it('describes windows', () => {
    expect(windowText({ start_basis: 'AGE', start_value: 60, end_basis: 'AGE', end_value: 75 })).toBe('age 60 to age 75')
    expect(windowText({ start_basis: 'YEARS_AFTER_RETIREMENT', start_value: 0, end_basis: 'AGE', end_value: null })).toBe('from retirement on')
  })

  it('lists goals with plan impact and toggles one off', async () => {
    let saved: { enabled?: boolean } = {}
    server.use(
      http.get('*/api/spending-goals', () =>
        HttpResponse.json({
          goals: [travel],
          costs: [{ id: 1, name: 'Travel', enabled: true, lifetime_real: 180000, lifetime_nominal: 250000, first_age: 55, last_age: 69 }],
          lifetime_real: 180000,
          lifetime_nominal: 250000,
        }),
      ),
      http.get('*/api/spending-goals/presets', () => HttpResponse.json(presets)),
      http.get('*/api/spending-goals/impact', () =>
        HttpResponse.json({ has_goals: true, success_rate_with: 0.8, success_rate_without: 0.9, success_rate_change: -0.1, target_success_rate: 0.85 }),
      ),
      http.put('*/api/spending-goals/1', async ({ request }) => {
        saved = (await request.json()) as typeof saved
        return HttpResponse.json({ ...travel, enabled: false })
      }),
    )
    render(<SpendingGoalsCard />)
    expect(await screen.findByText(/80%/)).toBeInTheDocument()
    expect(screen.getByText(/below your 85% target/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }))
    await waitFor(() => expect(saved.enabled).toBe(false))
  })

  it('adds a goal from a preset', async () => {
    let body: { name?: string; annual_amount?: number } = {}
    server.use(
      http.get('*/api/spending-goals', () => HttpResponse.json({ goals: [], costs: [], lifetime_real: 0, lifetime_nominal: 0 })),
      http.get('*/api/spending-goals/presets', () => HttpResponse.json(presets)),
      http.get('*/api/spending-goals/impact', () => HttpResponse.json({ has_goals: false })),
      http.post('*/api/spending-goals', async ({ request }) => {
        body = (await request.json()) as typeof body
        return HttpResponse.json({ ...travel, id: 2 }, { status: 201 })
      }),
    )
    render(<SpendingGoalsCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add Travel' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(body.name).toBe('Travel'))
    expect(body.annual_amount).toBe(12000)
  })
})
