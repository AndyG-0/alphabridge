import { useCallback, useSyncExternalStore } from 'react'

const KEY = 'ab-privacy'
export const MASK = '$•••••'
const listeners = new Set<() => void>()

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

let on = read()

/** True when balances should be masked. Plain function so formatters like `usd()` can call it outside React. */
export const isPrivate = () => on

export function setPrivate(next: boolean) {
  on = next
  try {
    localStorage.setItem(KEY, next ? '1' : '0')
  } catch {
    /* private browsing: the choice just won't persist */
  }
  listeners.forEach((l) => l())
}

export function usePrivacy(): [boolean, () => void] {
  const value = useSyncExternalStore(
    (cb) => {
      listeners.add(cb)
      return () => listeners.delete(cb)
    },
    () => on,
  )
  const toggle = useCallback(() => setPrivate(!on), [])
  return [value, toggle]
}
