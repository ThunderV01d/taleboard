import { useState } from "react"

import { DeleteDialog } from "@/components/delete-dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  REGISTRY_NAMES,
  useDeleteEntry,
  useLocations,
  useUsage,
  type Entry,
  type RegistryKind,
  type ScenesChoice,
  type Usage,
} from "@/lib/registries"

/**
 * The delete confirmation for a registry entry, listing where the entry is used first.
 *
 * - A character or prop: every layer showing it is removed, so the shots that lose one are listed.
 * - A location: a scene can't exist without one, so its scenes must either move to another location or be deleted
 *   (with their shots) -- the user picks which before Delete is enabled.
 */
export function EntryDeleteDialog({
  projectId,
  kind,
  entry,
  onDeleted,
  onClose,
}: {
  projectId: string
  kind: RegistryKind
  entry: Entry
  onDeleted: () => void
  onClose: () => void
}) {
  const usage = useUsage(projectId, kind, entry.id)
  const locations = useLocations(projectId)
  const deleteEntry = useDeleteEntry(projectId, kind)
  const [choice, setChoice] = useState<"move" | "delete" | null>(null)
  const [moveTo, setMoveTo] = useState("")
  const one = REGISTRY_NAMES[kind].one

  const used = (usage.data?.scenes.length ?? 0) > 0
  const otherLocations = (locations.data ?? []).filter((l) => l.id !== entry.id)

  // A location in use needs a decision; anything else just needs its usage loaded
  const scenes: ScenesChoice | null =
    kind !== "locations" || !used
      ? { deleteScenes: true }
      : choice === "move" && moveTo
        ? { moveTo }
        : choice === "delete"
          ? { deleteScenes: true }
          : null

  return (
    <DeleteDialog
      thing={one}
      name={entry.name}
      consequence={
        kind === "locations"
          ? "will be deleted."
          : "will be deleted, and removed from every shot it appears in."
      }
      confirmDisabled={!usage.isSuccess || scenes === null}
      onConfirm={async () => {
        await deleteEntry.mutateAsync({ entryId: entry.id, scenes: scenes! })
        onDeleted()
      }}
      onClose={onClose}
    >
      {usage.isPending ? (
        <p className="text-sm text-muted-foreground">
          Checking where it's used...
        </p>
      ) : usage.isError ? (
        <p className="text-sm text-destructive">
          Couldn't check where it's used: {usage.error.message}
        </p>
      ) : !used ? (
        <p className="text-sm text-muted-foreground">
          It isn't used in any {kind === "locations" ? "scene" : "shot"}.
        </p>
      ) : kind === "locations" ? (
        <div className="space-y-3 text-sm">
          <p>It's the location of these scenes:</p>
          <UsageList usage={usage.data} withShots={false} />
          <p>What should happen to them?</p>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="scenes-choice"
              className="mt-1"
              checked={choice === "move"}
              disabled={otherLocations.length === 0}
              onChange={() => setChoice("move")}
            />
            <span className="flex-1 space-y-2">
              <span className="block">Move them to another location</span>
              {otherLocations.length === 0 ? (
                <span className="block text-xs text-muted-foreground">
                  There's no other location to move them to.
                </span>
              ) : (
                choice === "move" && (
                  <Select value={moveTo} onValueChange={setMoveTo}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Choose a location" />
                    </SelectTrigger>
                    <SelectContent>
                      {otherLocations.map((location) => (
                        <SelectItem key={location.id} value={location.id}>
                          {location.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )
              )}
            </span>
          </label>
          <label className="flex items-start gap-2">
            <input
              type="radio"
              name="scenes-choice"
              className="mt-1"
              checked={choice === "delete"}
              onChange={() => setChoice("delete")}
            />
            <span>Delete them, with all their shots</span>
          </label>
        </div>
      ) : (
        <div className="space-y-2 text-sm">
          <p>It will be removed from these shots:</p>
          <UsageList usage={usage.data} withShots />
        </div>
      )}
    </DeleteDialog>
  )
}

/**
 * The scenes (and shots in them) an entry is used in, numbered as in the editor.
 */
function UsageList({ usage, withShots }: { usage: Usage; withShots: boolean }) {
  return (
    <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-3">
      {usage.scenes.map((scene) => (
        <li key={scene.scene_id}>
          <span className="font-medium">
            Scene {scene.order + 1}: {scene.name || "Untitled scene"}
          </span>
          {withShots && (
            <span className="text-muted-foreground">
              {" "}
              -- shot{scene.shots.length === 1 ? "" : "s"}{" "}
              {scene.shots.map((shot) => shot.order + 1).join(", ")}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
