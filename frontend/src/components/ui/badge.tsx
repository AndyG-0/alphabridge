import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

const badgeVariants = cva('rounded-full px-2 py-0.5 text-xs font-medium', {
  variants: {
    tone: {
      slate: 'bg-slate-800 text-slate-300',
      green: 'bg-emerald-900/60 text-emerald-300',
      amber: 'bg-amber-900/60 text-amber-300',
      red: 'bg-red-900/60 text-red-300',
    },
  },
  defaultVariants: { tone: 'slate' },
})

export function Badge({ className, tone, ...p }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span {...p} className={cn(badgeVariants({ tone }), className)} />
}
