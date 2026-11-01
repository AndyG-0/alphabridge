import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import Onboarding from './Onboarding'

const steps = [
  { id: 'household', title: 'Household', blurb: 'Who is this plan for?', done: false, skipped: false },
  { id: 'accounts', title: 'Accounts', blurb: 'Add accounts', done: false, skipped: false },
  { id: 'upload', title: 'Upload', blurb: 'Import statements', done: false, skipped: false },
  { id: 'goals', title: 'Goals', blurb: 'Set targets', done: false, skipped: false },
  { id: 'plan', title: 'First plan', blurb: 'Run it', done: false, skipped: false },
]
const completeness = {
  score: 35,
  inputs: [
    { key: 'income', label: 'Annual income', weight: 10, filled: false, improves: 'tax and savings projections', where: 'Plan page' },
    { key: 'accounts', label: 'Accounts', weight: 15, filled: true, improves: 'balances', where: 'Portfolio' },
  ],
  next_best: null,
}
const profile = { name: 'Me', birth_date: '1985-01-01', annual_income: 0, tax_filing_status: 'SINGLE', target_retirement_age: 55 }

function setup(current = 'household') {
  const puts: unknown[] = []
  server.use(
    http.get('*/api/onboarding', () => HttpResponse.json({ current, steps, completed: false, dismissed: false, show: true, first_run: false, completeness })),
    http.put('*/api/onboarding', async ({ request }) => {
      puts.push(await request.json())
      return HttpResponse.json({})
    }),
    http.get('*/api/profile', () => HttpResponse.json(profile)),
    http.put('*/api/profile', async () => HttpResponse.json(profile)),
  )
  render(
    <MemoryRouter>
      <Onboarding />
    </MemoryRouter>,
  )
  return puts
}

describe('Onboarding', () => {
  it('resumes at the server-reported step and shows what missing data would improve', async () => {
    setup('goals')
    expect(await screen.findByRole('heading', { name: 'Goals' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Age you want to stop working/)).toBeInTheDocument()
    expect(screen.getByText(/improves tax and savings projections/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Data completeness' })).toHaveAttribute('aria-valuenow', '35')
  })

  it('skipping a step records it', async () => {
    const puts = setup('upload')
    await userEvent.click(await screen.findByRole('button', { name: 'Skip for now' }))
    await waitFor(() => expect(puts).toContainEqual({ skip: 'upload' }))
  })

  it('saves the household profile and advances', async () => {
    const puts = setup()
    await userEvent.type(await screen.findByLabelText('Your first name'), 'Sam')
    await userEvent.click(screen.getByRole('button', { name: 'Save and continue' }))
    await waitFor(() => expect(puts).toContainEqual({ step: 'accounts' }))
  })
})
