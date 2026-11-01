import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import App from './App'
import { ApiError, getToken, setToken } from './api/client'
import { server } from './test/setup'

beforeEach(() => {
  localStorage.clear()
  // Unmocked endpoints fail: pages must survive the loading and error states without crashing.
  server.use(http.all('*/api/*', () => HttpResponse.json({ error: 'down' }, { status: 503 })))
})

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )

describe('App shell', () => {
  it('renders the bottom navigation with every page', async () => {
    renderAt('/')
    for (const label of ['Command', 'Plan', 'Portfolio', 'Analyst', 'Ask AI', 'Settings']) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0)
    }
  })

  it.each(['Plan', 'Portfolio', 'Analyst', 'Ask AI', 'Settings'])('navigates to %s without crashing', async (label) => {
    const user = userEvent.setup()
    renderAt('/')
    await user.click((await screen.findAllByText(label))[0])
    await waitFor(() => expect(document.body).toBeInTheDocument())
  })

  it('links every page to its own URL', async () => {
    renderAt('/')
    const hrefs = Object.fromEntries(
      ['Command', 'Plan', 'Portfolio', 'Analyst', 'Ask AI', 'Settings'].map((l) => [l, screen.getAllByText(l)[0].closest('a')?.getAttribute('href')]),
    )
    expect(hrefs).toEqual({ Command: '/', Plan: '/plan', Portfolio: '/portfolio', Analyst: '/research', 'Ask AI': '/chat', Settings: '/settings' })
  })

  it('opens a page directly from its URL and falls back to home for unknown paths', async () => {
    renderAt('/chat/7')
    expect(await screen.findByText('Ask the AI')).toBeInTheDocument()
    cleanup()
    renderAt('/nope')
    expect(screen.getAllByText('Command')[0].closest('a')).toHaveClass('text-emerald-400')
  })

  it('shows the unlock screen after a 401', async () => {
    server.use(http.all('*/api/*', () => HttpResponse.json({ error: 'unauthorized' }, { status: 401 })))
    renderAt('/')
    expect(await screen.findByText('Unlock')).toBeInTheDocument()
  })
})

describe('api client', () => {
  it('stores the bearer token', () => {
    setToken('abc')
    expect(getToken()).toBe('abc')
  })

  it('ApiError carries the status', () => {
    expect(new ApiError(404, 'nope').status).toBe(404)
  })
})
