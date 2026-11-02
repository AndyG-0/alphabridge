import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import CoverageOptionsCard, { formatPrices, parsePrices } from './CoverageOptionsCard'

const opt = {
  id: 1,
  name: 'HSC2',
  carrier: 'UHC',
  plan_code: '',
  category: 'PRE_MEDICARE',
  premium_by_year: { '2026': 1461 },
  premium_period: 'MONTHLY',
  premium_basis: 'PER_PERSON',
  deductible: 0,
  oop_max: 0,
  eligibility_min_age: 55,
  eligibility_max_age: null,
  requires_medicare_parts: '',
  requires_part_b_premium: false,
  includes_drugs: false,
  drug_option_id: null,
  owner: 'BOTH',
  cost_sharing_note: '',
  source_note: '',
  verified: false,
  active: true,
  sort_order: 0,
}

describe('CoverageOptionsCard', () => {
  it('parses and formats price lists', () => {
    expect(parsePrices('2026: 1616, 2027: 1700.5, bad')).toEqual({ '2026': 1616, '2027': 1700.5 })
    expect(formatPrices({ '2026': 5 })).toBe('2026: 5')
  })

  it('lists options, flags unverified, and saves a choice', async () => {
    let chosen: unknown = null
    server.use(
      http.get('*/api/coverage-options', () => HttpResponse.json({ options: [opt], choice: {} })),
      http.put('*/api/coverage-choice', async ({ request }) => {
        chosen = await request.json()
        return HttpResponse.json({ choice: { SELF: 1 } })
      }),
    )
    render(<CoverageOptionsCard />)
    expect(await screen.findByText(/from age 55/)).toBeInTheDocument()
    expect(screen.getByText('unverified')).toBeInTheDocument()
    expect(screen.getByText(/from age 55/)).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Your coverage'), '1')
    expect(chosen).toEqual({ SELF: 1 })
  })

  it('posts a new option from the form', async () => {
    let body: { name?: string; premium_by_year?: unknown } = {}
    server.use(
      http.get('*/api/coverage-options', () => HttpResponse.json({ options: [], choice: {} })),
      http.post('*/api/coverage-options', async ({ request }) => {
        body = (await request.json()) as typeof body
        return HttpResponse.json({ ...opt, id: 2 }, { status: 201 })
      }),
    )
    render(<CoverageOptionsCard />)
    await userEvent.click(await screen.findByRole('button', { name: 'Add option' }))
    await userEvent.type(screen.getByLabelText('Name'), 'Surest')
    await userEvent.type(screen.getByLabelText(/Premiums by year/), '2026: 1616')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(body.name).toBe('Surest')
    expect(body.premium_by_year).toEqual({ '2026': 1616 })
  })
})
