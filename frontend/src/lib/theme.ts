import { useCallback, useSyncExternalStore } from 'react'

export type Theme = 'dark' | 'light'
const KEY = 'ab-theme'

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'dark' || v === 'light' ? v : null
  } catch {
    return null
  }
}

export function resolveTheme(): Theme {
  return stored() ?? (window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark')
}

const listeners = new Set<() => void>()

export function applyTheme(t: Theme) {
  document.documentElement.dataset.theme = t
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', t === 'light' ? '#f8fafc' : '#0b1220')
}

export function useTheme(): [Theme, () => void] {
  const theme = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'),
  )
  const toggle = useCallback(() => {
    const next: Theme = theme === 'light' ? 'dark' : 'light'
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* private mode: theme just won't persist */
    }
    applyTheme(next)
    listeners.forEach((l) => l())
  }, [theme])
  return [theme, toggle]
}
