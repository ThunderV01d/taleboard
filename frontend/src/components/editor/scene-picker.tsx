import {
  CheckIcon,
  ChevronDownIcon,
  EllipsisIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"
import { useState } from "react"

import { SortableItem, SortableList } from "@/components/sortable"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { ATMOSPHERE_LABELS, TIME_OF_DAY_LABELS } from "@/lib/labels"
import type { Location } from "@/lib/registries"
import type { Scene } from "@/lib/scenes"
import { cn } from "@/lib/utils"

/**
 * The scene picker under the project name: the current scene, a list of every scene to switch to (drag one by its
 * grip to reorder), "+ New scene" at the end -- and a menu to edit or delete the current scene.
 */
export function ScenePicker({
  scenes,
  locations,
  current,
  onSelect,
  onReorder,
  onNew,
  onEdit,
  onDelete,
}: {
  scenes: Scene[]
  locations: Location[]
  current: Scene | null
  onSelect: (scene: Scene) => void
  onReorder: (sceneIds: string[]) => void
  onNew: () => void
  onEdit: (scene: Scene) => void
  onDelete: (scene: Scene) => void
}) {
  const [open, setOpen] = useState(false)
  const number = (scene: Scene) => scenes.indexOf(scene) + 1

  return (
    <div className="flex min-w-0 items-center gap-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            className="h-auto min-w-0 justify-between gap-3 py-1.5 text-left"
          >
            {current ? (
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-medium">
                  Scene {number(current)}: {current.name || "Untitled scene"}
                </span>
                <span className="truncate text-xs font-normal text-muted-foreground">
                  <SceneMeta scene={current} locations={locations} />
                </span>
              </span>
            ) : (
              <span className="text-muted-foreground">No scenes yet</span>
            )}
            <ChevronDownIcon className="shrink-0 text-muted-foreground" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 p-1">
          {scenes.length > 0 && (
            <SortableList ids={scenes.map((s) => s.id)} onReorder={onReorder}>
              <ol className="max-h-80 overflow-y-auto">
                {scenes.map((scene) => (
                  <SortableItem
                    key={scene.id}
                    id={scene.id}
                    className="rounded-md bg-popover"
                  >
                    {(grip) => (
                      <div
                        className={cn(
                          "flex items-center gap-1 rounded-md px-1 hover:bg-muted",
                          scene.id === current?.id && "bg-muted"
                        )}
                      >
                        {grip}
                        <button
                          className="flex min-w-0 flex-1 flex-col items-start py-1.5 text-left"
                          onClick={() => {
                            onSelect(scene)
                            setOpen(false)
                          }}
                        >
                          <span className="w-full truncate text-sm">
                            {number(scene)}. {scene.name || "Untitled scene"}
                          </span>
                          <span className="w-full truncate text-xs text-muted-foreground">
                            <SceneMeta scene={scene} locations={locations} />
                          </span>
                        </button>
                        {scene.id === current?.id && (
                          <CheckIcon className="mr-1 size-4 shrink-0" />
                        )}
                      </div>
                    )}
                  </SortableItem>
                ))}
              </ol>
            </SortableList>
          )}
          <button
            className="mt-1 flex w-full items-center gap-2 rounded-md border-t px-2 py-2 text-sm hover:bg-muted"
            onClick={() => {
              setOpen(false)
              onNew()
            }}
          >
            <PlusIcon className="size-4" />
            New scene
          </button>
        </PopoverContent>
      </Popover>

      {current && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Scene actions">
              <EllipsisIcon />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => onEdit(current)}>
              <PencilIcon />
              Edit scene
            </DropdownMenuItem>
            <DropdownMenuItem
              variant="destructive"
              onSelect={() => onDelete(current)}
            >
              <Trash2Icon />
              Delete scene
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  )
}

/**
 * "Lighthouse · Night · Foggy"
 */
function SceneMeta({
  scene,
  locations,
}: {
  scene: Scene
  locations: Location[]
}) {
  const location =
    locations.find((l) => l.id === scene.location_id)?.name ?? scene.location_id
  return (
    <>
      {location} · {TIME_OF_DAY_LABELS[scene.time_of_day]} ·{" "}
      {ATMOSPHERE_LABELS[scene.atmosphere]}
    </>
  )
}
