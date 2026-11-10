import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core"
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { GripVerticalIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * A list whose items can be dragged into a new order -- by a grip handle on each item, so clicking the rest of the
 * item still does its normal job.
 *
 * A drag only starts once the pointer has moved a few pixels with the button down, so a slightly shaky click never
 * reorders anything. The grip also works from the keyboard (space to pick up, arrows to move, space to drop).
 * `onReorder` gets the full list of IDs in their new order.
 */
export function SortableList({
  ids,
  direction = "vertical",
  onReorder,
  children,
}: {
  ids: string[]
  direction?: "vertical" | "horizontal"
  onReorder: (ids: string[]) => void
  children: ReactNode
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  const end = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) {
      onReorder(
        arrayMove(
          ids,
          ids.indexOf(String(active.id)),
          ids.indexOf(String(over.id))
        )
      )
    }
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={end}
    >
      <SortableContext
        items={ids}
        strategy={
          direction === "vertical"
            ? verticalListSortingStrategy
            : horizontalListSortingStrategy
        }
      >
        {children}
      </SortableContext>
    </DndContext>
  )
}

/**
 * One item in a SortableList. `children` gets the grip to place wherever suits the item -- none, when it can't be moved
 * (`disabled`, in a project that's read-only).
 */
export function SortableItem({
  id,
  className,
  disabled = false,
  children,
}: {
  id: string
  className?: string
  disabled?: boolean
  children: (grip: ReactNode) => ReactNode
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id, disabled })

  const grip = disabled ? null : (
    <button
      ref={setActivatorNodeRef}
      type="button"
      aria-label="Drag to reorder"
      className="shrink-0 cursor-grab touch-none rounded p-0.5 text-muted-foreground hover:text-foreground active:cursor-grabbing"
      {...attributes}
      {...listeners}
    >
      <GripVerticalIcon className="size-3.5" />
    </button>
  )

  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      className={cn(
        className,
        isDragging && "relative z-10 opacity-80 shadow-md"
      )}
    >
      {children(grip)}
    </li>
  )
}
