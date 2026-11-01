import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export function Card({ className, ...p }: HTMLAttributes<HTMLElement>) {
  return <section {...p} className={cn('rounded-2xl border border-border bg-card p-4 text-card-foreground', className)} />
}

export function CardTitle({ className, children, ...p }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 {...p} className={cn('mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground', className)}>
      {children}
    </h2>
  )
}
