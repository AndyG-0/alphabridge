// Stable app-facing API; the primitives behind it are shadcn/ui-style components in ./ui/.
import { Info } from 'lucide-react'
import { useId } from 'react'
import type { InputHTMLAttributes, ReactNode } from 'react'
import { isPrivate, MASK } from '../lib/privacy'
import { cn } from '../lib/utils'
import { Badge as BadgeBase } from './ui/badge'
import { Button } from './ui/button'
import { Card as CardBase, CardTitle } from './ui/card'
import { InputControl } from './ui/input'
import { Popover, PopoverContent, PopoverTrigger } from './ui/popover'

export { Button }

export const usd = (n: number | null | undefined) =>
  n == null ? '—' : isPrivate() ? MASK : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
export const pct = (n: number | null | undefined, d = 1) => (n == null ? '—' : `${(n * 100).toFixed(d)}%`)

export function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <CardBase className={className}>
      {title && <CardTitle>{title}</CardTitle>}
      {children}
    </CardBase>
  )
}

/** Info icon with a popover on click, tap or keyboard (Radix handles focus, Esc and outside-click). */
export function Hint({ children }: { children: ReactNode }) {
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="More info"
          className="rounded-full text-slate-500 hover:text-slate-300 focus-visible:outline-2 focus-visible:outline-ring"
        >
          <Info size={14} />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start">{children}</PopoverContent>
    </Popover>
  )
}

export function Input({ label, hint, className, ...p }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: ReactNode }) {
  const id = useId()
  if (!hint) {
    return (
      <label className="block text-sm text-slate-300">
        {label}
        <InputControl {...p} className={className} />
      </label>
    )
  }
  // hint sits outside the <label> so clicking its link doesn't focus the input
  return (
    <div className="text-sm text-slate-300">
      <div className="flex items-center gap-1.5">
        <label htmlFor={id}>{label}</label>
        <Hint>{hint}</Hint>
      </div>
      <InputControl id={id} {...p} className={className} />
    </div>
  )
}

export function Err({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p role="alert" className="mt-2 rounded-lg bg-red-950/60 p-2 text-sm text-red-300">
      {error instanceof Error ? error.message : String(error)}
    </p>
  )
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' }) {
  return <BadgeBase tone={tone}>{children}</BadgeBase>
}

export function Bar({ value, tone = 'bg-emerald-500' }: { value: number; tone?: string }) {
  return (
    <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
      <div className={cn('h-full rounded-full', tone)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}
