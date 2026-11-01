import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { server } from '../test/setup'
import ImportHistoryCard from './ImportHistoryCard'

const row = {
  filename: 'p.csv',
  parser: 'csv',
  rows: 3,
  message: '',
  created_at: '2026-05-04T10:00:00',
  account: 'Brokerage',
  batch_id: 'b',
  content_hash: 'abc',
  undone_at: null,
}

describe('ImportHistoryCard', () => {
  it('lists imports and offers undo only where allowed', async () => {
    let undone = 0
    server.use(
      http.get('*/api/ingest/log', () =>
        HttpResponse.json([
          { ...row, id: 2, status: 'OK', can_undo: true },
          { ...row, id: 1, status: 'OK', can_undo: false },
        ]),
      ),
      http.post('*/api/ingest/2/undo', () => {
        undone += 1
        return HttpResponse.json({ undone: [2] })
      }),
    )
    const changed = vi.fn()
    render(<ImportHistoryCard version={0} onChanged={changed} />)
    const buttons = await screen.findAllByRole('button', { name: 'Undo' })
    expect(buttons).toHaveLength(1)
    await userEvent.click(buttons[0])
    expect(undone).toBe(1)
    expect(changed).toHaveBeenCalled()
  })
})
