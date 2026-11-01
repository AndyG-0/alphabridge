import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import AssumptionsCard from './AssumptionsCard'
import ScenarioCard from './ScenarioCard'
import SurvivorCard from './SurvivorCard'

describe('planning cards', () => {
  it('shows survivor tax, estate flag and the checklist', async () => {
    server.use(
      http.get('*/api/planner/survivor', () =>
        HttpResponse.json({
          married: true,
          deceased: 'SPOUSE',
          social_security: { household_before: 4500, household_after: 3000, monthly_lost: 1500 },
          death_of_spouse: {
            tax_before: 5000,
            tax_after: 9000,
            tax_increase: 4000,
            income_before: 100000,
            income_after: 90000,
            spend_after: 60000,
            after_tax_surplus_after: 21000,
            widows_penalty: true,
          },
          estate: { net_worth: 2000000, exclusion: 30000000, estimated_tax: 0, flag: 'OK', headroom: 1 },
          beneficiaries: { accounts: [{ account: 'IRA', balance: 1000, check: 'Confirm beneficiaries' }], retitling: [{ item: 'HSA', note: 'Spouse only' }] },
          insurance: { life_need: 1000000, life_gap: 400000, disability_target_monthly: 5000, disability_gap_monthly: 3000 },
          defaults: { verified: false, notes: '', source_url: '' },
        }),
      ),
    )
    render(<SurvivorCard />)
    expect(await screen.findByText(/widow/)).toBeInTheDocument()
    expect(screen.getByText('OK')).toBeInTheDocument()
    expect(screen.getByText(/not read directly from irs.gov/)).toBeInTheDocument()
  })

  it('lists presets and saved scenarios', async () => {
    server.use(
      http.get('*/api/planner/scenarios', () =>
        HttpResponse.json({ saved: [{ id: 3, name: 'Retire at 52', overrides: {}, shock: 0 }], presets: [{ name: 'crash_30', label: 'Market falls 30%' }] }),
      ),
    )
    render(<ScenarioCard />)
    expect(await screen.findByText(/Market falls 30%/)).toBeInTheDocument()
    expect(screen.getByText(/Retire at 52/)).toBeInTheDocument()
  })

  it('shows plan health parts and editable assumptions', async () => {
    server.use(
      http.get('*/api/planner/assumptions', () =>
        HttpResponse.json({
          overridden: 0,
          assumptions: [
            { key: 'inflation', label: 'Inflation', group: 'inflation', default: 0.025, value: 0.025, min: 0, max: 0.1, source: 's', overridden: false },
          ],
        }),
      ),
      http.get('*/api/planner/health', () =>
        HttpResponse.json({
          health: { score: 82, grade: 'OK', parts: [{ name: 'Bridge funding', weight: 25, points: 20, why: 'covers 80%' }] },
          diff: { has_previous: false, metrics: [], assumptions: [] },
          last_run_at: null,
        }),
      ),
    )
    render(<AssumptionsCard />)
    expect(await screen.findByText(/82\/100/)).toBeInTheDocument()
    expect(screen.getByLabelText('Inflation')).toHaveValue(0.025)
  })

  it('compares picked scenarios, runs the solver and saves an edited assumption', async () => {
    const m = { success_rate: 0.8, bridge_success_rate: 0.9, median_final_real: 1000000, retire_age: 55, monthly_spend: 5000 }
    let saved: unknown = null
    server.use(
      http.get('*/api/planner/scenarios', () => HttpResponse.json({ saved: [], presets: [{ name: 'crash_30', label: 'Market falls 30%' }] })),
      http.get('*/api/planner/scenarios/compare', () =>
        HttpResponse.json({
          base: m,
          scenarios: [{ name: 'crash_30', kind: 'preset', metrics: { ...m, success_rate: 0.6 }, vs_base: { success_rate: -0.2 } }],
        }),
      ),
      http.get('*/api/planner/tornado', () =>
        HttpResponse.json({
          base_success: 0.8,
          bars: [{ input: 'inflation', low_label: '-1pt', high_label: '+1pt', low_delta: 0.03, high_delta: -0.04, swing: 0.07 }],
        }),
      ),
      http.get('*/api/planner/solve', () => HttpResponse.json({ kind: 'max_spend', value: 6000, unit: '$/month', current: 5000, target_success: 0.85 })),
      http.get('*/api/planner/assumptions', () =>
        HttpResponse.json({
          overridden: 1,
          assumptions: [
            { key: 'inflation', label: 'Inflation', group: 'inflation', default: 0.025, value: 0.03, min: 0, max: 0.1, source: 's', overridden: true },
          ],
        }),
      ),
      http.put('*/api/planner/assumptions', async ({ request }) => {
        saved = await request.json()
        return HttpResponse.json({ overridden: 0, assumptions: [] })
      }),
      http.get('*/api/planner/health', () =>
        HttpResponse.json({
          health: { score: 70, grade: 'OK', parts: [] },
          diff: { has_previous: true, metrics: [], assumptions: [] },
          last_run_at: 'x',
        }),
      ),
    )
    const user = userEvent.setup()
    const { unmount } = render(<ScenarioCard />)
    await user.click(await screen.findByLabelText(/Market falls 30%/))
    await user.click(screen.getByRole('button', { name: /Compare/ }))
    expect(await screen.findByText(/-20.0 pts/)).toBeInTheDocument()
    expect(await screen.findByText(/inflation/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Solve/ }))
    expect(await screen.findByText(/\$\/month/)).toBeInTheDocument()
    unmount()
    render(<AssumptionsCard />)
    await user.click(await screen.findByRole('button', { name: 'reset' }))
    expect(saved).toEqual({ overrides: { inflation: null } })
  })
})
