import { cn } from 'cn'
import {
  Group,
  Panel,
  Separator,
  type GroupProps,
  type PanelProps,
  type SeparatorProps,
} from 'react-resizable-panels'

export function ResizablePanelGroup({ className, ...props }: GroupProps) {
  return (
    <Group
      data-slot="resizable-panel-group"
      className={cn('h-full w-full', className)}
      {...props}
    />
  )
}

export function ResizablePanel(props: PanelProps) {
  return <Panel data-slot="resizable-panel" {...props} />
}

export function ResizableHandle({ className, ...props }: SeparatorProps) {
  return (
    <Separator
      data-slot="resizable-handle"
      className={cn(
        'group/handle relative flex w-px shrink-0 items-center justify-center bg-border outline-none transition-colors duration-150 data-[separator=active]:bg-primary data-[separator=focus]:bg-primary data-[separator=hover]:bg-primary/60',
        className,
      )}
      {...props}
    >
      <div className="z-10 flex h-8 w-1 shrink-0 rounded-full bg-muted-foreground/35 transition-colors group-data-[separator=active]/handle:bg-primary group-data-[separator=focus]/handle:bg-primary group-data-[separator=hover]/handle:bg-primary" />
    </Separator>
  )
}
