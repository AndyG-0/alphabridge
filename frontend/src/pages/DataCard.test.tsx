import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import DataCard from './DataCard'

describe('DataCard', () => {
  it('creates a read-only share link', async () => {
    server.use(http.post('*/api/export/share', () => HttpResponse.json({ token: '1.sig', expires: '2026-11-07T00:00:00+00:00' })))
    render(<DataCard />)
    await userEvent.click(screen.getByRole('button', { name: /Share report link/ }))
    expect(await screen.findByText(/\/api\/share\/1\.sig\/report\.pdf/)).toBeInTheDocument()
  })

  it('shows backend errors from Back up now', async () => {
    server.use(http.post('*/api/export/backup', () => HttpResponse.json({ error: 'set BACKUP_DEST first' }, { status: 400 })))
    render(<DataCard />)
    await userEvent.click(screen.getByRole('button', { name: 'Back up now' }))
    expect(await screen.findByText(/set BACKUP_DEST first/)).toBeInTheDocument()
  })
})
