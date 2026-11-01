import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import WatchlistCard from './WatchlistCard'

describe('WatchlistCard', () => {
  it('shows alerts and broken theses, and adds a watch', async () => {
    let added: unknown = null
    server.use(
      http.get('*/api/research/watchlist', () =>
        HttpResponse.json([
          {
            id: 1,
            symbol: 'XYZ',
            note: '',
            buy_below: 12.5,
            upside_alert: null,
            price: 12,
            dcf_value: 20,
            alerts: ['XYZ is at 12.00, at or below your buy-below 12.50'],
          },
        ]),
      ),
      http.get('*/api/research/theses', () =>
        HttpResponse.json([
          {
            id: 2,
            symbol: 'ABC',
            thesis: 'durable growth',
            status: 'ACTIVE',
            invalidated_on: null,
            criteria: [{ metric: 'revenue_growth', op: '<', value: 0.05, text: 'growth stalls', current: 0.02, triggered: true }],
            broken: [{ metric: 'revenue_growth', op: '<', value: 0.05, current: 0.02, triggered: true }],
          },
        ]),
      ),
      http.post('*/api/research/watchlist', async ({ request }) => {
        added = await request.json()
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    render(<WatchlistCard />)
    expect(await screen.findByText(/at or below your buy-below/)).toBeInTheDocument()
    expect(await screen.findByText('BROKEN')).toBeInTheDocument()
    expect(screen.getByText(/growth stalls/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Watch ticker'), 'nvda')
    await userEvent.click(screen.getAllByText('Add')[0])
    expect(added).toEqual({ symbol: 'NVDA', buy_below: null })
  })
})
