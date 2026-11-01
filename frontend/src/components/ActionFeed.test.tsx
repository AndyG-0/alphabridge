import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import ActionFeed from './ActionFeed'

const item = (key: string, priority: number, status = 'open') => ({
  key,
  kind: key.split(':')[0],
  title: `Do ${key}`,
  detail: 'Because.',
  priority,
  where: '/plan',
  dollars: 1500,
  status,
  snooze_until: status === 'snoozed' ? '2026-11-07' : null,
})

describe('ActionFeed', () => {
  afterEach(() => new Promise((r) => setTimeout(r, 50)))

  it('shows the top items with dollars and snoozes one', async () => {
    const calls: string[] = []
    server.use(
      http.get('*/api/actions', () =>
        HttpResponse.json({ items: [item('match:2026', 90), item('rebalance:2026-10', 55), item('stale:1', 40)], hidden: 2, high_priority: 1 }),
      ),
      http.post('*/api/actions/:key/snooze', ({ params }) => {
        calls.push(decodeURIComponent(String(params.key)))
        return HttpResponse.json({ ok: true })
      }),
    )
    render(
      <MemoryRouter>
        <ActionFeed limit={2} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Do match:2026')).toBeInTheDocument()
    expect(screen.queryByText('Do stale:1')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Worth about \$1,500/)).toHaveLength(2)
    expect(screen.getByRole('link', { name: /See all actions \(2 snoozed or done\)/ })).toHaveAttribute('href', '/actions')
    await userEvent.click(screen.getByRole('button', { name: 'Snooze 1 wk: Do match:2026' }))
    await waitFor(() => expect(calls).toEqual(['match:2026']))
  })

  it('shows snoozed items with a reopen button in the full view and an empty state otherwise', async () => {
    server.use(http.get('*/api/actions', () => HttpResponse.json({ items: [item('roth:2027', 60, 'snoozed')], hidden: 1, high_priority: 0 })))
    const { unmount } = render(
      <MemoryRouter>
        <ActionFeed showHidden />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Snoozed until 2026-11-07/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reopen: Do roth:2027' })).toBeInTheDocument()
    unmount()
    server.use(http.get('*/api/actions', () => HttpResponse.json({ items: [], hidden: 0, high_priority: 0 })))
    render(
      <MemoryRouter>
        <ActionFeed limit={5} />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Nothing needs your attention/)).toBeInTheDocument()
  })
})
