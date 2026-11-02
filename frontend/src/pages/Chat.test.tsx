import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { server } from '../test/setup'
import Chat from './Chat'

const Where = () => <div data-testid="where">{useLocation().pathname}</div>
const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/chat/:sessionId?" element={<Chat />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  )
const s1 = { id: 1, title: 'Retirement check', title_source: 'auto', updated_at: '2026-01-01', message_count: 2 }

describe('Chat sessions', () => {
  it('resumes a saved conversation from its URL', async () => {
    server.use(
      http.get('*/api/chat/sessions', () => HttpResponse.json([s1])),
      http.get('*/api/chat/sessions/1', () =>
        HttpResponse.json({
          ...s1,
          messages: [
            { id: 1, role: 'user', content: 'Am I ok?', tools: [] },
            { id: 2, role: 'assistant', content: 'Yes.', tools: ['get_profile'] },
          ],
        }),
      ),
    )
    renderAt('/chat/1')
    expect(await screen.findByText('Am I ok?')).toBeInTheDocument()
    expect(screen.getByText('Yes.')).toBeInTheDocument()
    expect(screen.getByText(/get_profile/)).toBeInTheDocument()
  })

  it('creates a session on first send and moves the URL to it', async () => {
    server.use(
      http.get('*/api/chat/sessions', () => HttpResponse.json([])),
      http.post('*/api/chat/sessions', () => HttpResponse.json({ ...s1, id: 5, messages: [] }, { status: 201 })),
      http.post('*/api/chat/sessions/5/messages', () =>
        HttpResponse.json({
          session: { ...s1, id: 5 },
          user: { id: 10, role: 'user', content: 'hello', tools: [] },
          assistant: { id: 11, role: 'assistant', content: 'hi there', tools: [] },
        }),
      ),
    )
    const user = userEvent.setup()
    renderAt('/chat')
    await user.type(screen.getByPlaceholderText('Ask about your plan…'), 'hello{Enter}')
    expect(await screen.findByText('hi there')).toBeInTheDocument()
    expect(screen.getByTestId('where')).toHaveTextContent('/chat/5')
  })

  it('renders assistant markdown but keeps user text plain', async () => {
    server.use(
      http.get('*/api/chat/sessions', () => HttpResponse.json([s1])),
      http.get('*/api/chat/sessions/1', () =>
        HttpResponse.json({
          ...s1,
          messages: [
            { id: 1, role: 'user', content: 'use **stars**', tools: [] },
            { id: 2, role: 'assistant', content: '**Yes** - see:\n\n- one\n- two', tools: [] },
          ],
        }),
      ),
    )
    renderAt('/chat/1')
    const bold = await screen.findByText('Yes', { selector: 'strong' })
    const reply = bold.closest('div')!
    expect(
      within(reply)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['one', 'two'])
    expect(screen.getByText('use **stars**')).toBeInTheDocument()
  })

  it('renames and deletes a session', async () => {
    let title = s1.title
    let deleted = false
    server.use(
      http.get('*/api/chat/sessions', () => HttpResponse.json(deleted ? [] : [{ ...s1, title }])),
      http.patch('*/api/chat/sessions/1', async ({ request }) => {
        title = ((await request.json()) as { title: string }).title
        return HttpResponse.json({ ...s1, title })
      }),
      http.delete('*/api/chat/sessions/1', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()
    renderAt('/chat')
    await user.click(await screen.findByLabelText('Rename Retirement check'))
    const box = screen.getByLabelText('Conversation title')
    await user.clear(box)
    await user.type(box, 'Cash plan{Enter}')
    expect(await screen.findByText('Cash plan')).toBeInTheDocument()
    await user.click(screen.getByLabelText('Delete Cash plan'))
    await waitFor(() => expect(screen.queryByText('Cash plan')).not.toBeInTheDocument())
  })

  it('shows the server footer and saves scenario notes', async () => {
    const patches: unknown[] = []
    server.use(
      http.get('*/api/chat/sessions', () => HttpResponse.json([s1])),
      http.get('*/api/chat/sessions/1', () =>
        HttpResponse.json({
          ...s1,
          scenario: 'Retire at 52',
          memory: 'Spouse works to 55',
          messages: [{ id: 2, role: 'assistant', content: 'Yes.', tools: ['get_profile'], footer: 'General information only. Prompt v1.' }],
        }),
      ),
      http.patch('*/api/chat/sessions/1', async ({ request }) => {
        patches.push(await request.json())
        return HttpResponse.json(s1)
      }),
    )
    renderAt('/chat/1')
    expect(await screen.findByText(/General information only/)).toBeInTheDocument()
    expect(await screen.findByDisplayValue('Retire at 52')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText(/Notes the assistant should remember/), '!')
    await userEvent.click(screen.getByRole('button', { name: 'Save notes' }))
    await waitFor(() => expect(patches).toEqual([{ scenario: 'Retire at 52', memory: 'Spouse works to 55!' }]))
    expect(await screen.findByText('Saved')).toBeInTheDocument()
  })
})
