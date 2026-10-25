import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router"

import { EnumSelect } from "@/components/enum-select"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { ATMOSPHERE_LABELS, TIME_OF_DAY_LABELS } from "@/lib/labels"
import { useLocations } from "@/lib/registries"
import { useSaveScene, type Scene, type SceneIn } from "@/lib/scenes"

/** The location dropdown's last option, which leaves for the location registry */
const NEW_LOCATION = "__new_location__"

/**
 * The Scene Creator panel -- or, given a scene, the panel for editing it.
 *
 * A scene happens in exactly one location, at one time of day, in one kind of weather; a change of any of them is a
 * new scene. Picking "+ New location" leaves for the location registry, dropping whatever was typed here (a
 * deliberate choice in the spec: it's a rare path, and most scenes reuse a location).
 */
export function SceneDialog({
  projectId,
  scene,
  onSaved,
  onClose,
}: {
  projectId: string
  scene?: Scene
  onSaved: (scene: Scene) => void
  onClose: () => void
}) {
  const navigate = useNavigate()
  const locations = useLocations(projectId)
  const saveScene = useSaveScene(projectId)
  const [draft, setDraft] = useState<SceneIn>({
    name: scene?.name ?? "",
    description: scene?.description ?? "",
    location_id: scene?.location_id ?? "",
    time_of_day: scene?.time_of_day ?? "day",
    atmosphere: scene?.atmosphere ?? "clear",
  })
  const [error, setError] = useState<string | null>(null)
  const change = (fields: Partial<SceneIn>) =>
    setDraft((current) => ({ ...current, ...fields }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      const saved = await saveScene.mutateAsync({
        sceneId: scene?.id,
        scene: { ...draft, name: draft.name.trim() },
      })
      onSaved(saved)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const pickLocation = (value: string) => {
    if (value === NEW_LOCATION) {
      onClose()
      navigate(`/projects/${projectId}/locations`)
    } else {
      change({ location_id: value })
    }
  }

  const busy = saveScene.isPending
  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{scene ? "Edit scene" : "New scene"}</DialogTitle>
            <DialogDescription>
              A scene stays in one place, at one time of day. When either
              changes, start a new scene.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="scene-name">Name</Label>
            <Input
              id="scene-name"
              autoFocus
              maxLength={100}
              placeholder="eg:- The lighthouse at night"
              value={draft.name}
              onChange={(e) => change({ name: e.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="scene-location">Location</Label>
            <Select value={draft.location_id} onValueChange={pickLocation}>
              <SelectTrigger id="scene-location" className="w-full">
                <SelectValue placeholder="Choose a location" />
              </SelectTrigger>
              <SelectContent>
                {locations.data?.map((location) => (
                  <SelectItem key={location.id} value={location.id}>
                    {location.name}
                  </SelectItem>
                ))}
                {(locations.data?.length ?? 0) > 0 && <SelectSeparator />}
                <SelectItem value={NEW_LOCATION}>+ New location</SelectItem>
              </SelectContent>
            </Select>
            {locations.data?.length === 0 && (
              <p className="text-xs text-muted-foreground">
                This project has no locations yet -- add one first.
              </p>
            )}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="scene-time">Time of day</Label>
              <EnumSelect
                id="scene-time"
                value={draft.time_of_day}
                labels={TIME_OF_DAY_LABELS}
                onChange={(time_of_day) => change({ time_of_day })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="scene-atmosphere">Weather</Label>
              <EnumSelect
                id="scene-atmosphere"
                value={draft.atmosphere}
                labels={ATMOSPHERE_LABELS}
                onChange={(atmosphere) => change({ atmosphere })}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="scene-description">Description</Label>
            <Textarea
              id="scene-description"
              rows={3}
              maxLength={2000}
              placeholder="What happens in this scene"
              value={draft.description}
              onChange={(e) => change({ description: e.target.value })}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !draft.location_id}>
              {busy ? "Saving..." : scene ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
