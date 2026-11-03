import {
  CloudCheckIcon,
  CloudUploadIcon,
  LoaderCircleIcon,
  Redo2Icon,
  SparklesIcon,
  TriangleAlertIcon,
  Undo2Icon,
} from "lucide-react"
import { useCallback, useEffect, useReducer, useRef, useState } from "react"
import { createPortal } from "react-dom"

import { LayersPanel } from "@/components/canvas/layers-panel"
import {
  LayerProperties,
  ShotProperties,
  type LayerEdit,
} from "@/components/canvas/properties-panel"
import {
  ShotCanvas,
  type TransformChange,
} from "@/components/canvas/shot-canvas"
import { ToolStrip, type Tool } from "@/components/canvas/tool-strip"
import { DeleteDialog } from "@/components/delete-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"
import type { GenerateTarget, LayerProgress } from "@/lib/generation"
import {
  FACING_LABELS,
  LAYER_TYPE_LABELS,
  ORIENTATION_LABELS,
} from "@/lib/labels"
import {
  addOnTop,
  descendantsOf,
  dropLayer,
  findLayer,
  hasBackground,
  newBackgroundLayer,
  newCharacterLayer,
  newGroupLayer,
  newImageLayer,
  newPropLayer,
  newTextLayer,
  removeLayers,
  updateLayer,
  type DropZone,
  type Layer,
} from "@/lib/layers"
import type { Character, Location, Prop } from "@/lib/registries"
import type { Scene } from "@/lib/scenes"
import {
  editorReducer,
  initialState,
  isDirty,
  onlyDrawnSince,
  toSaveBody,
  type Draft,
  type ShotFields,
} from "@/lib/shot-editor"
import { isUnwarped, type Corners } from "@/lib/warp"
import { fetchShot, useSaveShot, type Shot } from "@/lib/shots"
import { imageSize, uploadImage } from "@/lib/uploads"

/** How long the editor waits after the last change before saving it */
const AUTOSAVE_DELAY_MS = 1200

/** An uploaded image starts no bigger than this (in frame pixels) along its longer side */
const UPLOAD_FIT = 600

/** Where saving stands, as shown in the toolbar */
type SaveStatus = "saved" | "saving" | "failed" | "conflict"

/**
 * The canvas editor for one shot: the canvas, the layers panel, and the properties of what's selected.
 *
 * Changes save themselves a moment after you stop (and when you move to another shot). Each save sends the version it
 * was loaded at, so if the shot was saved somewhere else in the meantime -- another tab -- the save is refused and
 * you choose whose version to keep, rather than one silently overwriting the other.
 *
 * Generation saves images into the shot on the server while it's open; when a newer copy changes only that, it's
 * merged into the draft (and its undo history) -- a save racing it is merged and retried too -- so drawing never
 * shows as a conflict, and never undoes an edit.
 *
 * Mount it with key={shot.id}: everything here (the draft, undo history, selection) belongs to one shot.
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
}: {
  projectId: string
  scene: Scene
  shot: Shot
  characters: Character[]
  props: Prop[]
  locations: Location[]
  /** Where to draw undo/redo and the save status -- the page's toolbar row (nothing is drawn until it exists) */
  toolbarSlot: HTMLElement | null
  /** Where each layer stands with generation, by layer ID */
  progress: Record<string, LayerProgress>
  /** True while any of this shot's layers is waiting or being drawn */
  drawing: boolean
  /** Asks for layers to be drawn */
  onGenerate: (target: GenerateTarget) => Promise<unknown>
}) {
  const [state, dispatch] = useReducer(editorReducer, shot, initialState)
  const saveShot = useSaveShot(projectId, scene.id)
  const [status, setStatus] = useState<SaveStatus>("saved")
  const [problem, setProblem] = useState<string | null>(null)
  // The layers waiting on "Delete these layers?" (every delete asks first)
  const [confirmDelete, setConfirmDelete] = useState<string[] | null>(null)
  const [tool, setTool] = useState<Tool>("select")

  // The URL each image is drawn from, kept for the whole session: the first one known for it wins. Every save brings
  // back a fresh signed URL for every image, and switching to it would make the canvas download (and blink) each image
  // again after every edit. Uploads start with a URL for the file itself.
  const [knownUrls, setKnownUrls] = useState<Record<string, string>>(() => ({
    ...shot.image_urls,
  }))
  const learnUrls = (urls: Record<string, string>) =>
    setKnownUrls((known) => ({ ...urls, ...known }))

  // When the shot comes back from elsewhere with a newer version that changes nothing but what generation draws -- the
  // worker saving an image, or the deck saving a reorder -- merge it in, so the next save isn't refused as a conflict
  const [seenVersion, setSeenVersion] = useState(shot.version)
  if (shot.version !== seenVersion) {
    setSeenVersion(shot.version)
    if (
      shot.version > state.baseline.version &&
      onlyDrawnSince(state.baseline, shot)
    ) {
      dispatch({ type: "merge", shot })
      learnUrls(shot.image_urls)
    }
  }
  const latest = useRef(state)
  const saving = useRef(false)
  const failedDraft = useRef<Draft | null>(null)
  const dirty = isDirty(state)

  // What the callbacks below read, kept current on every render -- so `save` itself never changes, and the effects
  // that depend on it don't re-run (a useMutation result is a new object on every render)
  const mutateSave = useRef(saveShot.mutateAsync)
  const conflicted = useRef(false)
  useEffect(() => {
    latest.current = state
    mutateSave.current = saveShot.mutateAsync
    conflicted.current = status === "conflict"
  })

  /** Saves the draft if it needs it. Resolves to whether the server now has it (false if the save failed) */
  const save = useCallback(async (): Promise<boolean> => {
    let current = latest.current
    if (!isDirty(current)) {
      return true
    }
    if (saving.current) {
      return false
    }
    saving.current = true
    setStatus("saving")
    try {
      for (let attempt = 1; ; attempt++) {
        try {
          const saved = await mutateSave.current({
            shotId: shot.id,
            shot: toSaveBody(current),
          })
          dispatch({ type: "saved", shot: saved })
          learnUrls(saved.image_urls)
          setStatus("saved")
          setProblem(null)
          failedDraft.current = null
          return true
        } catch (error) {
          // Refused because generation saved an image meanwhile: merge it in, and save again on top of it
          if (
            error instanceof ApiError &&
            error.status === 409 &&
            attempt < 3
          ) {
            const newer = await fetchShot(projectId, scene.id, shot.id)
            if (onlyDrawnSince(current.baseline, newer)) {
              dispatch({ type: "merge", shot: newer })
              learnUrls(newer.image_urls)
              current = editorReducer(current, { type: "merge", shot: newer })
              continue
            }
          }
          throw error
        }
      }
    } catch (error) {
      failedDraft.current = current.draft
      if (error instanceof ApiError && error.status === 409) {
        setStatus("conflict")
      } else {
        setStatus("failed")
        setProblem(error instanceof Error ? error.message : String(error))
      }
      return false
    } finally {
      saving.current = false
    }
  }, [shot.id, projectId, scene.id])

  /** Asks for this shot's layers (or just one of them) to be drawn -- once the server has them all, saving first */
  const generate = async (layerId?: string) => {
    while (saving.current) {
      await new Promise((resolve) => setTimeout(resolve, 100)) // A save is already on its way
    }
    if (!(await save())) {
      return
    }
    try {
      await onGenerate({
        scene_id: scene.id,
        shot_id: shot.id,
        ...(layerId && { layer_id: layerId }),
      })
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  // Save a moment after the last change -- unless this exact draft already failed, or there's a conflict to settle
  useEffect(() => {
    if (
      !dirty ||
      status === "conflict" ||
      state.draft === failedDraft.current
    ) {
      return
    }
    const timer = setTimeout(() => void save(), AUTOSAVE_DELAY_MS)
    return () => clearTimeout(timer)
  }, [state.draft, dirty, status, save])

  // Leaving this shot (for another one) saves what's pending -- unless it's waiting on a conflict, or already failed;
  // leaving the page with unsaved changes asks first
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (isDirty(latest.current)) {
        event.preventDefault()
      }
    }
    window.addEventListener("beforeunload", warn)
    return () => {
      window.removeEventListener("beforeunload", warn)
      const pending = latest.current
      if (
        isDirty(pending) &&
        !saving.current &&
        !conflicted.current &&
        pending.draft !== failedDraft.current
      ) {
        void save()
      }
    }
  }, [save])

  /** Applies a change to the draft; `mergeKey` makes a run of changes to one field a single undo step */
  const edit = useCallback(
    (change: (draft: Draft) => Draft, mergeKey?: string, select?: string[]) =>
      dispatch({ type: "edit", change, mergeKey, select }),
    []
  )
  const editLayers = (
    change: (layers: Layer[]) => Layer[],
    mergeKey?: string,
    select?: string[]
  ) =>
    edit(
      (draft) => ({ ...draft, layers: change(draft.layers) }),
      mergeKey,
      select
    )

  const selection = state.selection
  const selected =
    selection.length === 1
      ? (findLayer(state.draft.layers, selection[0])?.layer ?? null)
      : null

  const editSelected: LayerEdit = (change, field) => {
    if (selected) {
      editLayers(
        (layers) => updateLayer(layers, selected.id, change),
        field && `${selected.id}:${field}`
      )
    }
  }

  const editFields = (change: Partial<ShotFields>, field: string) =>
    edit(
      (draft) => ({ ...draft, fields: { ...draft.fields, ...change } }),
      `shot:${field}`
    )

  const applyTransforms = (changes: TransformChange[]) =>
    editLayers((layers) =>
      changes.reduce(
        (list, { id, transform }) =>
          updateLayer(list, id, (l) => ({ ...l, transform })),
        layers
      )
    )

  // Corners back where they started are stored as none at all
  const warp = (id: string, corners: Corners) =>
    editLayers((layers) =>
      updateLayer(layers, id, (l) => ({
        ...l,
        corners: isUnwarped(corners) ? null : corners,
      }))
    )

  const add = (layer: Layer) =>
    editLayers((layers) => addOnTop(layers, layer), undefined, [layer.id])

  /** Uploads an image, then hands back its key -- showing any problem instead */
  const upload = async (
    file: File
  ): Promise<{ key: string; longest: number } | null> => {
    setProblem(null)
    try {
      const [key, size] = await Promise.all([
        uploadImage(projectId, file),
        imageSize(file),
      ])
      learnUrls({ [key]: URL.createObjectURL(file) })
      return { key, longest: Math.max(size.width, size.height) }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
      return null
    }
  }

  const addImage = async (file: File) => {
    const uploaded = await upload(file)
    if (uploaded) {
      const scale = Math.min(1, UPLOAD_FIT / uploaded.longest)
      const layer = newImageLayer(
        uploaded.key,
        file.name.replace(/\.[^.]+$/, "").slice(0, 100)
      )
      add({
        ...layer,
        transform: { ...layer.transform, scale_x: scale, scale_y: scale },
      })
    }
  }

  const replaceImage = async (file: File) => {
    const target = selected
    const uploaded = await upload(file)
    if (target && uploaded) {
      editLayers((layers) =>
        updateLayer(layers, target.id, (l) => ({ ...l, image: uploaded.key }))
      )
    }
  }

  // Every delete asks first; the background can be deleted too (the frame is then transparent)
  const deleteSelected = () => {
    if (selection.length > 0) {
      setConfirmDelete([...selection])
    }
  }

  const drop = (draggedId: string, targetId: string, zone: DropZone) => {
    const result = dropLayer(state.draft.layers, draggedId, targetId, zone)
    if (result) {
      editLayers(() => result.layers, undefined, [result.select])
    }
  }

  // A background goes at the very bottom of the stack; a shot has one at most
  const addBackground = () => {
    if (!hasBackground(state.draft.layers)) {
      const background = newBackgroundLayer()
      editLayers((layers) => [background, ...layers], undefined, [
        background.id,
      ])
    }
  }

  // Keyboard: undo/redo, save now, delete, V and D for the tools, and Escape to leave Distort or else deselect -- but
  // not while typing in a field
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.ctrlKey || event.metaKey
      if (mod && event.key.toLowerCase() === "s") {
        event.preventDefault()
        void save()
        return
      }
      const target = event.target as HTMLElement
      if (
        target.closest(
          "input, textarea, select, [contenteditable=true], [role=dialog], [role=menu]"
        )
      ) {
        return
      }
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault()
        dispatch({ type: event.shiftKey ? "redo" : "undo" })
      } else if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault()
        dispatch({ type: "redo" })
      } else if (event.key === "Escape") {
        if (tool === "distort") {
          setTool("select")
        } else {
          dispatch({ type: "select", ids: [] })
        }
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "v") {
        setTool("select")
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "d") {
        setTool("distort")
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault()
        deleteSelected()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  })

  const resolveConflict = async (keep: "mine" | "theirs") => {
    try {
      const latestShot = await fetchShot(projectId, scene.id, shot.id)
      learnUrls(latestShot.image_urls)
      if (keep === "theirs") {
        dispatch({ type: "load", shot: latestShot })
        setStatus("saved")
      } else {
        // Save this draft over their version: take the current version number, then save as usual
        dispatch({ type: "saved", shot: latestShot })
        failedDraft.current = null
        setStatus("saved")
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  const location = locations.find((l) => l.id === scene.location_id)

  const imageUrl = (layer: Layer): string | null => {
    if ("image" in layer && layer.image) {
      return knownUrls[layer.image] ?? null
    }
    // Not drawn yet: show the reference it will be drawn from, if there is one
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
      return plate ? (location.image_urls[plate] ?? null) : null
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

  const toolbar = (
    <>
      <Button
        variant="outline"
        size="icon-sm"
        title="Undo (Ctrl+Z)"
        aria-label="Undo"
        disabled={state.past.length === 0}
        onClick={() => dispatch({ type: "undo" })}
      >
        <Undo2Icon />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        title="Redo (Ctrl+Shift+Z)"
        aria-label="Redo"
        disabled={state.future.length === 0}
        onClick={() => dispatch({ type: "redo" })}
      >
        <Redo2Icon />
      </Button>
      <SaveIndicator status={status} dirty={dirty} onSave={() => void save()} />
      <Button
        variant="outline"
        size="sm"
        title="Draw every layer in this shot that isn't drawn yet, or has changed since"
        disabled={drawing}
        onClick={() => void generate()}
      >
        {drawing ? (
          <LoaderCircleIcon className="animate-spin" />
        ) : (
          <SparklesIcon />
        )}
        {drawing ? "Drawing..." : "Generate shot"}
      </Button>
    </>
  )

  return (
    <div className="flex min-h-0 flex-1">
      {toolbarSlot && createPortal(toolbar, toolbarSlot)}
      <aside
        className="flex w-80 shrink-0 border-r"
        aria-label="Tools and layers"
      >
        <ToolStrip tool={tool} onTool={setTool} />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <LayersPanel
              layers={state.draft.layers}
              selection={selection}
              characters={characters}
              props={props}
              onSelect={(ids) => dispatch({ type: "select", ids })}
              onToggleVisible={(id) =>
                editLayers((layers) =>
                  updateLayer(layers, id, (l) => ({
                    ...l,
                    visible: !l.visible,
                  }))
                )
              }
              canAddBackground={!hasBackground(state.draft.layers)}
              onDrop={drop}
              onDelete={deleteSelected}
              onAddBackground={addBackground}
              onAddText={() => add(newTextLayer())}
              onAddGroup={() => add(newGroupLayer())}
              onAddImage={(file) => void addImage(file)}
              onAddCharacter={(character) => add(newCharacterLayer(character))}
              onAddProp={(prop) => add(newPropLayer(prop))}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto border-t p-3">
            <ShotProperties fields={state.draft.fields} onEdit={editFields} />
          </div>
        </div>
      </aside>

      <section
        className="flex min-w-0 flex-1 flex-col gap-2 p-2"
        aria-label="Canvas"
      >
        {status === "conflict" && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>This shot was changed somewhere else</AlertTitle>
            <AlertDescription>
              <p>
                It was saved from another tab or device since you opened it, so
                your latest changes haven't been saved.
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void resolveConflict("theirs")}
                >
                  Load their version (lose my changes)
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void resolveConflict("mine")}
                >
                  Keep my version
                </Button>
              </div>
            </AlertDescription>
          </Alert>
        )}
        {problem && (
          <Alert variant="destructive">
            <AlertTitle>
              {status === "failed" ? "Couldn't save" : "Something went wrong"}
            </AlertTitle>
            <AlertDescription>{problem}</AlertDescription>
          </Alert>
        )}

        <div className="relative min-h-0 flex-1">
          <ShotCanvas
            layers={state.draft.layers}
            selection={selection}
            tool={tool}
            imageUrl={imageUrl}
            placeholderLabel={placeholderLabel}
            onSelect={(ids) => dispatch({ type: "select", ids })}
            onTransform={applyTransforms}
            onWarp={warp}
          />
          {tool === "distort" && (
            <p className="pointer-events-none absolute top-1 left-1/2 -translate-x-1/2 rounded-full border bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow-sm">
              Distort: drag a selected picture's corners. Esc or V to go back to
              Select.
            </p>
          )}
        </div>
      </section>

      <aside
        className="w-80 shrink-0 overflow-y-auto border-l p-4"
        aria-label="Layer details"
      >
        <LayerProperties
          selected={selected}
          selectionCount={selection.length}
          characters={characters}
          props={props}
          locationName={location?.name ?? scene.location_id}
          onEditLayer={editSelected}
          onReplaceImage={(file) => void replaceImage(file)}
          onDistort={() => setTool("distort")}
          progress={selected ? progress[selected.id] : undefined}
          onGenerate={(layerId) => void generate(layerId)}
        />
      </aside>

      {confirmDelete && (
        <DeleteLayersDialog
          layers={state.draft.layers}
          ids={confirmDelete}
          onConfirm={() =>
            editLayers(
              (layers) => removeLayers(layers, confirmDelete),
              undefined,
              []
            )
          }
          onClose={() => setConfirmDelete(null)}
        />
      )}
    </div>
  )
}

/**
 * "Delete this layer?" -- naming it, and listing everything inside any group being deleted (it all goes too).
 * Undo (Ctrl+Z) brings it back.
 */
function DeleteLayersDialog({
  layers,
  ids,
  onConfirm,
  onClose,
}: {
  layers: Layer[]
  ids: string[]
  onConfirm: () => void
  onClose: () => void
}) {
  const doomed = ids
    .map((id) => findLayer(layers, id)?.layer)
    .filter((layer): layer is Layer => layer !== undefined)
  const label = (layer: Layer) => layer.name || LAYER_TYPE_LABELS[layer.type]
  const inside = doomed.flatMap((layer) =>
    layer.type === "group" ? descendantsOf(layer) : []
  )
  const single = doomed.length === 1 ? doomed[0] : null

  return (
    <DeleteDialog
      thing={
        single
          ? LAYER_TYPE_LABELS[single.type].toLowerCase()
          : `${doomed.length} layers`
      }
      name={single ? label(single) : doomed.map(label).join(", ")}
      consequence={
        inside.length > 0
          ? `will be deleted, along with the layers inside ${single ? "it" : "them"} (listed below).`
          : "will be deleted."
      }
      confirmLabel="Delete"
      undoable
      onConfirm={async () => onConfirm()}
      onClose={onClose}
    >
      {inside.length > 0 && (
        <ul className="max-h-48 overflow-y-auto rounded-md border p-3 text-sm">
          {inside.map((layer) => (
            <li key={layer.id}>
              {label(layer)}{" "}
              <span className="text-muted-foreground">
                ({LAYER_TYPE_LABELS[layer.type].toLowerCase()})
              </span>
            </li>
          ))}
        </ul>
      )}
    </DeleteDialog>
  )
}

/**
 * Where saving stands: saved, saving, waiting to save, or a problem -- with "Save now" while there's anything to save.
 */
function SaveIndicator({
  status,
  dirty,
  onSave,
}: {
  status: SaveStatus
  dirty: boolean
  onSave: () => void
}) {
  const text =
    status === "saving"
      ? "Saving..."
      : status === "conflict"
        ? "Not saved -- changed elsewhere"
        : status === "failed"
          ? "Not saved"
          : dirty
            ? "Unsaved changes"
            : "All changes saved"
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      {status === "saving" || dirty ? (
        <CloudUploadIcon className="size-4" />
      ) : (
        <CloudCheckIcon className="size-4" />
      )}
      <span aria-live="polite">{text}</span>
      {dirty && status !== "saving" && status !== "conflict" && (
        <Button
          variant="outline"
          size="sm"
          title="Save now (Ctrl+S)"
          onClick={onSave}
        >
          Save now
        </Button>
      )}
    </div>
  )
}
