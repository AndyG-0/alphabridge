import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from './Markdown'

const md = (text: string) => render(<Markdown>{text}</Markdown>).container

describe('Markdown', () => {
  it('renders headings, emphasis and lists', () => {
    const c = md('## Summary\n\n**Yes**, *mostly* ~~no~~.\n\n- one\n- two\n\n1. first\n2. second')
    expect(screen.getByRole('heading', { level: 2, name: 'Summary' })).toBeInTheDocument()
    expect(c.querySelector('strong')).toHaveTextContent('Yes')
    expect(c.querySelector('em')).toHaveTextContent('mostly')
    expect(c.querySelector('del')).toHaveTextContent('no')
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
    expect(c.querySelector('ol')).toBeInTheDocument()
  })

  it('renders GFM tables and task lists', () => {
    const c = md('| Account | Balance |\n| --- | ---: |\n| 401k | $120,000 |\n\n- [x] done\n- [ ] todo')
    const table = screen.getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'Balance' })).toBeInTheDocument()
    expect(within(table).getByRole('cell', { name: '$120,000' })).toBeInTheDocument()
    const boxes = c.querySelectorAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(2)
    expect((boxes[0] as HTMLInputElement).checked).toBe(true)
  })

  it('renders inline code and fenced blocks', () => {
    const c = md('Use `SPAXX`.\n\n```\nx = 1\n```')
    expect(c.querySelector('p code')).toHaveTextContent('SPAXX')
    expect(c.querySelector('pre code')).toHaveTextContent('x = 1')
  })

  it('opens links in a new tab safely, including bare URLs', () => {
    md('[SEC](https://sec.gov) and https://fred.stlouisfed.org')
    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(2)
    for (const a of links) {
      expect(a).toHaveAttribute('target', '_blank')
      expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })

  it('does not render raw HTML and keeps dollar amounts literal', () => {
    const c = md('<img src=x onerror="alert(1)"><script>alert(1)</script>\n\nSave $1,000 and $2,000 a month.')
    expect(c.querySelector('img')).toBeNull()
    expect(c.querySelector('script')).toBeNull()
    expect(screen.getByText('Save $1,000 and $2,000 a month.')).toBeInTheDocument()
  })
})
