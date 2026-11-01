import clsx from 'clsx'
import { Info } from 'lucide-react'
import { useId } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

export const usd = (n: number | null | undefined) =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
export const pct = (n: number | null | undefined, d = 1) => (n == null ? '—' : `${(n * 100).toFixed(d)}%`)

export function Card({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={clsx('rounded-2xl border border-slate-800 bg-slate-900/70 p-4', className)}>
      {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">{title}</h2>}
      {children}
    </section>
  )
}

export function Button({ variant = 'primary', className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' }) {
  return (
    <button
      {...p}
      className={clsx(
        'rounded-xl px-4 py-2 text-sm font-medium transition disabled:opacity-50',
        variant === 'primary' ? 'bg-emerald-500 text-slate-950 hover:bg-emerald-400' : 'border border-slate-700 text-slate-200 hover:bg-slate-800',
        className,
      )}
    />
  )
}

const inputCls = 'mt-1 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100'

/** Info icon with a popover on hover, keyboard focus or tap; the pt-1 bridge keeps it open while the pointer moves onto a link. */
export function Hint({ children }: { children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      <button type="button" aria-label="More info" className="rounded-full text-slate-500 hover:text-slate-300 focus:text-slate-300 focus:outline-none">
        <Info size={14} />
      </button>
      <span className="absolute left-0 top-full z-20 hidden w-72 max-w-[80vw] pt-1 group-hover:block group-focus-within:block">
        <span className="block rounded-xl border border-slate-700 bg-slate-900 p-3 text-xs font-normal text-slate-300 shadow-lg">{children}</span>
      </span>
    </span>
  )
}

export function Input({ label, hint, className, ...p }: InputHTMLAttributes<HTMLInputElement> & { label?: string; hint?: ReactNode }) {
  const id = useId()
  if (!hint) {
    return (
      <label className="block text-sm text-slate-300">
        {label}
        <input {...p} className={clsx(inputCls, className)} />
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
      <input id={id} {...p} className={clsx(inputCls, className)} />
    </div>
  )
}

export function Err({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="mt-2 rounded-lg bg-red-950/60 p-2 text-sm text-red-300">{error instanceof Error ? error.message : String(error)}</p>
}

export function Badge({ children, tone = 'slate' }: { children: ReactNode; tone?: 'slate' | 'green' | 'amber' | 'red' }) {
  const t = {
    slate: 'bg-slate-800 text-slate-300',
    green: 'bg-emerald-900/60 text-emerald-300',
    amber: 'bg-amber-900/60 text-amber-300',
    red: 'bg-red-900/60 text-red-300',
  }[tone]
  return <span className={clsx('rounded-full px-2 py-0.5 text-xs font-medium', t)}>{children}</span>
}

export function Bar({ value, tone = 'bg-emerald-500' }: { value: number; tone?: string }) {
  return (
    <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
      <div className={clsx('h-full rounded-full', tone)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  )
}
