import type { InputHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

export function InputControl({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...p}
      className={cn(
        'mt-1 w-full rounded-xl border border-input bg-background px-3 py-2 text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50',
        className,
      )}
    />
  )
}
