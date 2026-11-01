import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { describe, expect, it } from 'vitest'
import { applyTheme, useTheme } from '../lib/theme'
import { Badge, Bar, Button, Card, Err, Hint, Input, pct, usd } from './ui'

function ThemeProbe() {
  const [t, toggle] = useTheme()
  return <button onClick={toggle}>theme:{t}</button>
}

describe('ui primitives', () => {
  it('formats money and percent with placeholders for null', () => {
    expect(usd(1234.5)).toBe('$1,235')
    expect(usd(null)).toBe('—')
    expect(pct(0.1234)).toBe('12.3%')
    expect(pct(undefined)).toBe('—')
  })

  it('renders Card title, Badge, Bar clamp and Err only with an error', () => {
    const { container, rerender } = render(
      <Card title="Hello">
        <Badge tone="green">ok</Badge>
        <Bar value={250} />
        <Err error={null} />
      </Card>,
    )
    expect(screen.getByRole('heading', { name: 'Hello' })).toBeInTheDocument()
    expect(container.querySelector('[style]')).toHaveStyle({ width: '100%' })
    expect(screen.queryByRole('alert')).toBeNull()
    rerender(<Err error={new Error('boom')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
  })

  it('Button asChild-free variants render and Input links label', () => {
    render(
      <>
        <Button variant="ghost">go</Button>
        <Input label="Amount" />
      </>,
    )
    expect(screen.getByRole('button', { name: 'go' })).toBeInTheDocument()
    expect(screen.getByLabelText('Amount')).toBeInTheDocument()
  })

  it('Hint opens on click and closes on Escape (keyboard accessible)', async () => {
    const user = userEvent.setup()
    render(<Hint>help text</Hint>)
    await user.click(screen.getByRole('button', { name: 'More info' }))
    expect(await screen.findByText('help text')).toBeVisible()
    await user.keyboard('{Escape}')
    expect(screen.queryByText('help text')).toBeNull()
  })

  it('theme toggles the data-theme attribute and persists', async () => {
    applyTheme('dark')
    const user = userEvent.setup()
    render(<ThemeProbe />)
    expect(screen.getByRole('button')).toHaveTextContent('theme:dark')
    await act(() => user.click(screen.getByRole('button')))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('ab-theme')).toBe('light')
  })
})
