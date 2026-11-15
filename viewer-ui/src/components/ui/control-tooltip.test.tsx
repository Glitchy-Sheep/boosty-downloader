import { act, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { ControlTooltip } from '@/components/ui/control-tooltip'
import { TooltipActive } from '@/lib/tooltip-activity'

test.each(['scope', 'control'] as const)(
  'a hidden %s closes its portal and does not reopen it on return',
  async (owner) => {
    const control = (active: boolean) => (
      <TooltipActive value={owner === 'scope' ? active : true}>
        <ControlTooltip label="Photo filter" active={owner === 'control' ? active : true}>
          <button type="button">Photos</button>
        </ControlTooltip>
      </TooltipActive>
    )
    const view = render(control(true))
    const trigger = screen.getByRole('button', { name: 'Photos' })
    act(() => trigger.focus())
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Photo filter')
    view.rerender(control(false))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    view.rerender(control(true))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
    act(() => {
      trigger.blur()
      trigger.focus()
    })
    expect(await screen.findByRole('tooltip')).toBeInTheDocument()
  },
)
