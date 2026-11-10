import { LoaderCircleIcon, SparklesIcon } from "lucide-react"

import {
  CanvasEditor,
  type Loaded,
  type Persist,
} from "@/components/canvas/canvas-editor"
import { ShotProperties } from "@/components/canvas/properties-panel"
import { Button } from "@/components/ui/button"
import { onlyDrawnSince } from "@/lib/canvas-editor"
import type { GenerateTarget, LayerProgress } from "@/lib/generation"
import { FACING_LABELS, ORIENTATION_LABELS } from "@/lib/labels"
import type { Layer } from "@/lib/layers"
import type { Character, Location, Prop } from "@/lib/registries"
import type { Scene } from "@/lib/scenes"
import {
  fetchShot,
  savedShot,
  useSaveShot,
  type Shot,
  type ShotFields,
} from "@/lib/shots"

/** A shot as the editor holds it, with its image URLs */
function loaded(shot: Shot): Loaded<ShotFields> {
  return { saved: savedShot(shot), imageUrls: shot.image_urls }
}

/**
 * The canvas editor for one shot: its layers (background, characters, props and the rest), its framing, and drawing
 * what generation draws.
 *
 * Generation saves images into the shot on the server while it's open; when a newer copy changes only that, it's
 * merged into the draft (and its undo history) -- a save racing it is merged and retried too -- so drawing never
 * shows as a conflict, and never undoes an edit.
 *
 * Mount it with key={shot.id}: everything in it (the draft, undo history, selection) belongs to one shot.
 */
export function ShotEditor({
  projectId,
  scene,
  shot,
  characters,
  props,
  locations,
  toolbarSlot,
  progress,
  drawing,
  onGenerate,
  readOnly = false,
}: {
  projectId: string
  scene: Scene
  shot: Shot
  characters: Character[]
  props: Prop[]
  locations: Location[]
  /** Where to draw undo/redo, the save status and "Generate shot" -- the page's toolbar row */
  toolbarSlot: HTMLElement | null
  /** Where each layer stands with generation, by layer ID */
  progress: Record<string, LayerProgress>
  /** True while any of this shot's layers is waiting or being drawn */
  drawing: boolean
  /** Asks for layers to be drawn */
  onGenerate: (target: GenerateTarget) => Promise<unknown>
  /** Looking only -- the project is shared with the user to view */
  readOnly?: boolean
}) {
  const saveShot = useSaveShot(projectId, scene.id)
  const location = locations.find((l) => l.id === scene.location_id)

  const persist: Persist<ShotFields> = {
    save: async (draft, version) =>
      loaded(
        await saveShot.mutateAsync({
          shotId: shot.id,
          shot: { ...draft.fields, layers: draft.layers, version },
        })
      ),
    fetch: async () => loaded(await fetchShot(projectId, scene.id, shot.id)),
    mergeable: onlyDrawnSince,
  }

  // Not drawn yet: show the reference it will be drawn from, if there is one
  const undrawnUrl = (layer: Layer): string | null => {
    if (layer.type === "character") {
      const character = characters.find((c) => c.id === layer.character_id)
      const reference = character?.references[layer.orientation]
      return reference ? (character!.image_urls[reference.image] ?? null) : null
    }
    if (layer.type === "prop") {
      const prop = props.find((p) => p.id === layer.prop_id)
      const reference = prop?.references[layer.orientation]
      return reference ? (prop!.image_urls[reference.image] ?? null) : null
    }
    if (layer.type === "background" && location) {
      const plate = location.plates[layer.facing]
      return plate ? (location.image_urls[plate.image] ?? null) : null
    }
    return null
  }

  const waitingLabel = (layer: Layer): string => {
    switch (layer.type) {
      case "background":
        return `Background -- not drawn yet\n${location?.name ?? scene.location_id}, facing ${FACING_LABELS[layer.facing].toLowerCase()}`
      case "character":
      case "prop":
        return `${layer.name}\n${ORIENTATION_LABELS[layer.orientation].toLowerCase()}`
      default:
        return layer.name || "Image"
    }
  }

  /** What a not-yet-drawn layer's placeholder says -- with where it's up to, while it's being drawn */
  const placeholderLabel = (layer: Layer): string => {
    const where = progress[layer.id]
    const status =
      where?.state === "drawing"
        ? "Drawing..."
        : where?.state === "waiting"
          ? "Waiting to be drawn"
          : where?.state === "failed"
            ? "Couldn't be drawn"
            : null
    return status ? `${status}\n${waitingLabel(layer)}` : waitingLabel(layer)
  }

  return (
    <CanvasEditor<ShotFields>
      projectId={projectId}
      noun="shot"
      document={savedShot(shot)}
      imageUrls={shot.image_urls}
      persist={persist}
      toolbarSlot={toolbarSlot}
      readOnly={readOnly}
      toolbar={({ generate, dirty }) =>
        readOnly ? null : (
          <Button
            variant="outline"
            size="sm"
            title={
              !dirty && Object.keys(shot.out_of_date).length === 0
                ? "Every layer in this shot is drawn and up to date"
                : "Draw every layer in this shot that isn't drawn yet, or has changed since"
            }
            // Unsaved edits might put a layer out of date -- the save before drawing finds out
            disabled={
              drawing || (!dirty && Object.keys(shot.out_of_date).length === 0)
            }
            onClick={() => void generate()}
          >
            {drawing ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <SparklesIcon />
            )}
            {drawing ? "Drawing..." : "Generate shot"}
          </Button>
        )
      }
      fields={(fields, onEdit) => (
        <ShotProperties fields={fields} onEdit={onEdit} />
      )}
      characters={characters}
      props={props}
      registryLayers
      undrawnUrl={undrawnUrl}
      placeholderLabel={placeholderLabel}
      locationName={location?.name ?? scene.location_id}
      progress={progress}
      outOfDate={shot.out_of_date}
      onGenerate={(layerId) =>
        onGenerate({
          scene_id: scene.id,
          shot_id: shot.id,
          ...(layerId && { layer_id: layerId }),
        })
      }
    />
  )
}
