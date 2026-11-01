import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { usd } from '../components/ui'
import { isPrivate, MASK, setPrivate, usePrivacy } from './privacy'

afterEach(() => setPrivate(false))

describe('privacy mode', () => {
  it('masks currency through usd() and restores it', () => {
    expect(usd(1234)).toBe('$1,234')
    setPrivate(true)
    expect(usd(1234)).toBe(MASK)
    expect(usd(null)).toBe('—') // missing stays missing, it is not a balance
    setPrivate(false)
    expect(usd(1234)).toBe('$1,234')
  })

  it('persists the choice and notifies subscribers', () => {
    const { result } = renderHook(() => usePrivacy())
    expect(result.current[0]).toBe(false)
    act(() => result.current[1]())
    expect(result.current[0]).toBe(true)
    expect(isPrivate()).toBe(true)
    expect(localStorage.getItem('ab-privacy')).toBe('1')
  })
})
