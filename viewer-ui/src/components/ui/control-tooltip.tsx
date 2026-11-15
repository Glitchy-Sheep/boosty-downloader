import { Tooltip } from 'radix-ui'
import { useContext, useState, type ReactElement } from 'react'

import { TooltipActive } from '@/lib/tooltip-activity'

type ControlTooltipProps = { label: string; children: ReactElement; active?: boolean }

export function ControlTooltip({ label, children, active = true }: ControlTooltipProps) {
  const parentActive = useContext(TooltipActive)
  const visible = active && parentActive
  const [open, setOpen] = useState(false)
  if (!visible && open) setOpen(false)
  return (
    <Tooltip.Provider delayDuration={350}>
      <Tooltip.Root open={visible && open} onOpenChange={setOpen}>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            sideOffset={6}
            className="z-70 rounded-lg border bg-popover px-2.5 py-1.5 text-[13px] text-popover-foreground shadow-lg"
          >
            {label}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  )
}
