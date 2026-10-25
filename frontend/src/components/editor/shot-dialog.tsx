import { useState, type FormEvent } from "react"

import { EnumSelect } from "@/components/enum-select"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { Textarea } from "@/components/ui/textarea"
import { ANGLE_LABELS, FACING_LABELS, SHOT_SIZE_LABELS } from "@/lib/labels"
import { characterLayers } from "@/lib/layers"
import { useCharacters } from "@/lib/registries"
import {
  toSave,
  useCreateShot,
  useSaveShot,
  type Shot,
  type ShotIn,
} from "@/lib/shots"
import type { components } from "@/api/schema"

type Facing = components["schemas"]["Facing"]

/**
 * The Shot Creator panel: a blank shot's framing, which way the camera faces, and who's in it.
 *
 * The API creates a shot with just its background; when a facing other than north or any characters are chosen, the
 * new shot is saved once more with those layers added -- two requests, but the shot is never half-made for long.
 */
export function ShotDialog({
  projectId,
  sceneId,
  onCreated,
  onClose,
}: {
  projectId: string
  sceneId: string
  onCreated: (shot: Shot) => void
  onClose: () => void
}) {
  const characters = useCharacters(projectId)
  const createShot = useCreateShot(projectId, sceneId)
  const saveShot = useSaveShot(projectId, sceneId)
  const [draft, setDraft] = useState<ShotIn>({
    description: "",
    duration_s: 2,
    shot_size: "medium",
    angle: "eye_level",
    details: "",
  })
  const [facing, setFacing] = useState<Facing>("north")
  const [cast, setCast] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const change = (fields: Partial<ShotIn>) =>
    setDraft((current) => ({ ...current, ...fields }))

  const toggle = (characterId: string, on: boolean) =>
    setCast((current) =>
      on
        ? [...current, characterId]
        : current.filter((id) => id !== characterId)
    )

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      let shot = await createShot.mutateAsync(draft)
      const chosen = (characters.data ?? []).filter((c) => cast.includes(c.id))
      if (facing !== "north" || chosen.length > 0) {
        const layers = [
          ...shot.layers.map((layer) =>
            layer.type === "background" ? { ...layer, facing } : layer
          ),
          ...characterLayers(chosen),
        ]
        shot = await saveShot.mutateAsync({
          shotId: shot.id,
          shot: { ...toSave(shot), layers },
        })
      }
      onCreated(shot)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New shot</DialogTitle>
            <DialogDescription>
              Set up the framing -- everything can be changed on the canvas
              afterwards.
            </DialogDescription>
          </DialogHeader>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label htmlFor="shot-size">Shot size</Label>
              <EnumSelect
                id="shot-size"
                value={draft.shot_size}
                labels={SHOT_SIZE_LABELS}
                onChange={(shot_size) => change({ shot_size })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="shot-angle">Angle</Label>
              <EnumSelect
                id="shot-angle"
                value={draft.angle}
                labels={ANGLE_LABELS}
                onChange={(angle) => change({ angle })}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="shot-facing">Facing</Label>
              <EnumSelect
                id="shot-facing"
                value={facing}
                labels={FACING_LABELS}
                onChange={setFacing}
              />
            </div>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Characters</legend>
            {characters.data?.length ? (
              <div className="grid grid-cols-2 gap-2">
                {characters.data.map((character) => (
                  <label
                    key={character.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <Checkbox
                      checked={cast.includes(character.id)}
                      onCheckedChange={(on) =>
                        toggle(character.id, on === true)
                      }
                    />
                    {character.name}
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                No characters yet -- add them in the Characters registry.
              </p>
            )}
          </fieldset>
          <div className="space-y-2">
            <Label htmlFor="shot-description">Description</Label>
            <Textarea
              id="shot-description"
              rows={2}
              maxLength={2000}
              placeholder="What happens in this shot (not drawn)"
              value={draft.description}
              onChange={(e) => change({ description: e.target.value })}
            />
          </div>
          <div className="grid grid-cols-[1fr_auto] gap-4">
            <div className="space-y-2">
              <Label htmlFor="shot-details">Details in the location</Label>
              <Input
                id="shot-details"
                maxLength={150}
                placeholder="eg:- the door is open"
                value={draft.details}
                onChange={(e) => change({ details: e.target.value })}
              />
            </div>
            <div className="w-24 space-y-2">
              <Label htmlFor="shot-duration">Seconds</Label>
              <Input
                id="shot-duration"
                type="number"
                min={0.1}
                max={60}
                step={0.1}
                required
                value={draft.duration_s}
                onChange={(e) => change({ duration_s: Number(e.target.value) })}
              />
            </div>
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
            <Button type="submit" disabled={busy}>
              {busy ? "Creating..." : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
