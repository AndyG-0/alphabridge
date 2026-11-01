import * as PopoverPrimitive from '@radix-ui/react-popover'
import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

export const Popover = PopoverPrimitive.Root
export const PopoverTrigger = PopoverPrimitive.Trigger

export function PopoverContent({ className, sideOffset = 6, ...p }: ComponentProps<typeof PopoverPrimitive.Content>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        sideOffset={sideOffset}
        {...p}
        className={cn(
          'z-50 w-72 max-w-[80vw] rounded-xl border border-border bg-popover p-3 text-xs font-normal text-popover-foreground shadow-lg outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0',
          className,
        )}
      />
    </PopoverPrimitive.Portal>
  )
}
