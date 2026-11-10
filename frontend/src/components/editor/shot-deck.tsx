import {
  EllipsisIcon,
  LoaderCircleIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"

import { SortableItem, SortableList } from "@/components/sortable"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { ANGLE_LABELS, SHOT_SIZE_LABELS } from "@/lib/labels"
import { shotFreshness } from "@/lib/staleness"
import type { Shot } from "@/lib/shots"
import { cn } from "@/lib/utils"

/**
 * The shot deck along the bottom of the editor: the scene's shots in order, then "+" for a new one. Drag a shot by
 * its grip to move it; click it to open it. Each says how many of its layers are out of date or not drawn yet.
 */
export function ShotDeck({
  shots,
  selectedId,
  onSelect,
  onNew,
  onReorder,
  onDelete,
  drawing,
  readOnly = false,
}: {
  shots: Shot[]
  selectedId: string | null
  onSelect: (shot: Shot) => void
  onNew: () => void
  onReorder: (shotIds: string[]) => void
  onDelete: (shot: Shot) => void
  /** IDs of the shots with a layer waiting or being drawn */
  drawing: Set<string>
  /** Opening shots only -- no new shot, reordering or deleting (a project shared to view) */
  readOnly?: boolean
}) {
  return (
    // Padded, so a card's highlight (drawn just outside it) isn't clipped by the scrolling row
    <ol className="flex gap-3 overflow-x-auto p-1.5" aria-label="Shots">
      <SortableList
        ids={shots.map((shot) => shot.id)}
        direction="horizontal"
        onReorder={onReorder}
      >
        {shots.map((shot, i) => (
          <SortableItem
            key={shot.id}
            id={shot.id}
            disabled={readOnly}
            className={cn(
              "relative flex w-60 shrink-0 rounded-lg border bg-card transition-shadow",
              shot.id === selectedId
                ? "ring-2 ring-primary"
                : "hover:ring-1 hover:ring-foreground/30"
            )}
          >
            {(grip) => (
              <>
                <div className="flex items-center pl-1">{grip}</div>
                <button
                  className="flex min-w-0 flex-1 items-start gap-2 py-2 pr-8 text-left"
                  aria-current={shot.id === selectedId}
                  onClick={() => onSelect(shot)}
                >
                  <span className="flex size-12 shrink-0 items-center justify-center rounded bg-muted text-lg font-semibold text-muted-foreground">
                    {i + 1}
                  </span>
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate text-xs font-medium">
                      {SHOT_SIZE_LABELS[shot.shot_size]} ·{" "}
                      {ANGLE_LABELS[shot.angle]}
                    </span>
                    <span className="line-clamp-2 text-xs text-muted-foreground">
                      {shot.description || "No description"}
                    </span>
                    {drawing.has(shot.id) ? (
                      <span className="flex items-center gap-1 text-xs text-primary">
                        <LoaderCircleIcon className="size-3 animate-spin" />
                        Drawing
                      </span>
                    ) : (
                      <PictureStatus shot={shot} />
                    )}
                  </span>
                </button>
                {!readOnly && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="secondary"
                        size="icon-xs"
                        className="absolute top-2 right-2"
                        aria-label={`Actions for shot ${i + 1}`}
                      >
                        <EllipsisIcon />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => onDelete(shot)}
                      >
                        <Trash2Icon />
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </>
            )}
          </SortableItem>
        ))}
      </SortableList>
      {!readOnly && (
        <li className="shrink-0">
          <button
            className="flex h-full min-h-16 w-32 items-center justify-center gap-1 rounded-lg border border-dashed text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground"
            onClick={onNew}
          >
            <PlusIcon className="size-4" />
            New shot
          </button>
        </li>
      )}
    </ol>
  )
}

/**
 * A shot's layers that need drawing: how many are out of date (an amber dot) and how many aren't drawn yet -- nothing,
 * if every one is up to date.
 */
function PictureStatus({ shot }: { shot: Shot }) {
  const { stale, undrawn } = shotFreshness(shot)
  if (stale === 0 && undrawn === 0) {
    return null
  }
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <span
        className={cn(
          "size-2 shrink-0 rounded-full",
          stale > 0 ? "bg-amber-500" : "border border-muted-foreground"
        )}
      />
      {[
        stale > 0 && `${stale} out of date`,
        undrawn > 0 && `${undrawn} not drawn`,
      ]
        .filter(Boolean)
        .join(" · ")}
    </span>
  )
}
