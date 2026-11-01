import { describe, expect, it } from 'vitest'
import en from './en.json'
import { t } from './index'

const sources = import.meta.glob('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

describe('i18n', () => {
  it('every key passed to t() exists in en.json', () => {
    const used = new Set<string>()
    for (const [file, text] of Object.entries(sources)) {
      if (file.includes('/i18n/')) continue
      for (const m of text.matchAll(/\bt\(\s*'([\w.]+)'/g)) used.add(m[1])
      for (const m of text.matchAll(/label:\s*'(nav\.[\w.]+)'/g)) used.add(m[1]) // keys stored in data and translated at render time
    }
    expect(used.size).toBeGreaterThan(10)
    const missing = [...used].filter((k) => !(k in en))
    expect(missing).toEqual([])
  })

  it('has no empty strings and fills placeholders', () => {
    expect(Object.values(en).every((v) => v.trim().length > 0)).toBe(true)
    expect(t('nav.chat')).toBe('Ask AI')
  })
})
