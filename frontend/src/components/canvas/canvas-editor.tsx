import {
  CloudCheckIcon,
  CloudUploadIcon,
  EyeIcon,
  Redo2Icon,
  TriangleAlertIcon,
  Undo2Icon,
} from "lucide-react"
import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { createPortal } from "react-dom"

import { LayersPanel } from "@/components/canvas/layers-panel"
import {
  LayerProperties,
  type LayerEdit,
} from "@/components/canvas/properties-panel"
import { PenBar } from "@/components/canvas/pen-bar"
import {
  ShotCanvas,
  type CanvasHandle,
  type TransformChange,
} from "@/components/canvas/shot-canvas"
import { ToolStrip, type Pen, type Tool } from "@/components/canvas/tool-strip"
import { ZoomBar } from "@/components/canvas/zoom-bar"
import { DeleteDialog } from "@/components/delete-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"
import {
  editorReducer,
  initialState,
  isDirty,
  type Draft,
  type EditorAction,
  type EditorState,
  type Saved,
} from "@/lib/canvas-editor"
import {
  MAX_STROKE_POINTS,
  strokePoints,
  type FreehandLayer,
  type Stroke,
} from "@/lib/freehand"
import type { LayerProgress } from "@/lib/generation"
import { LAYER_TYPE_LABELS } from "@/lib/labels"
import { freshness } from "@/lib/staleness"
import {
  addOnTop,
  descendantsOf,
  dropLayer,
  findLayer,
  hasBackground,
  newBackgroundLayer,
  newCharacterLayer,
  newFreehandLayer,
  newGroupLayer,
  newImageLayer,
  newPropLayer,
  newTextLayer,
  removeLayers,
  SHOT_FRAME,
  updateLayer,
  type DropZone,
  type Frame,
  type Layer,
} from "@/lib/layers"
import type { Character, Prop } from "@/lib/registries"
import { imageSize, uploadImage } from "@/lib/uploads"
import { isUnwarped, type Corners } from "@/lib/warp"
import { FIT, ZOOM_STEP, zoomAt, type View } from "@/lib/zoom"

/** How long the editor waits after the last change before saving it */
const AUTOSAVE_DELAY_MS = 1200

/** An uploaded image starts no bigger than this (in frame pixels) along its longer side -- unless it fills the frame */
const UPLOAD_FIT = 600

/** Where saving stands, as shown in the toolbar */
type SaveStatus = "saved" | "saving" | "failed" | "conflict"

/** Where the scale lock is remembered (in this browser) between shots and visits */
const SCALE_LOCK_KEY = "taleboard.scaleLocked"

function readScaleLock(): boolean {
  try {
    return localStorage.getItem(SCALE_LOCK_KEY) === "true"
  } catch {
    return false
  }
}

function writeScaleLock(locked: boolean): void {
  try {
    localStorage.setItem(SCALE_LOCK_KEY, String(locked))
  } catch {
    // Storage unavailable -- it's just not remembered
  }
}

/** A copy of the document from the API: its content and version, and a download URL for each of its images */
export type Loaded<F> = { saved: Saved<F>; imageUrls: Record<string, string> }

/** How the document is saved and loaded */
export type Persist<F> = {
  /** Saves the draft over `version` -- rejecting with a 409 ApiError if it's been saved since */
  save: (draft: Draft<F>, version: number) => Promise<Loaded<F>>
  /** Loads the latest copy, fresh */
  fetch: () => Promise<Loaded<F>>
  /**
   * True when a newer copy differs from the baseline only in what's safe to take in without asking (a shot's
   * generated images) -- it's then merged into the draft rather than treated as a conflict. Defaults to never.
   */
  mergeable?: (baseline: Saved<F>, newer: Saved<F>) => boolean
}

/** What the toolbar's own buttons can ask the editor to do (and whether there's anything unsaved) */
export type EditorActions = {
  /** Whether there are edits not saved yet */
  dirty: boolean
  /** Saves the draft if it needs it. Resolves to whether the server now has it (false if the save failed) */
  save: () => Promise<boolean>
  /** Saves, then asks for layers to be drawn (all of them, or one) -- for a document that's generated */
  generate: (layerId?: string) => Promise<void>
  /** What the frame shows, as a PNG */
  flatten: () => Promise<Blob>
  /** Shows a problem over the canvas (null clears it) */
  setProblem: (problem: string | null) => void
}

/**
 * The canvas editor: the canvas, the layers panel, and the properties of what's selected -- for one document with a
 * layer graph, a shot or a sketch.
 *
 * Changes save themselves a moment after you stop (and when you leave it). Each save sends the version it was loaded
 * at, so if the document was saved somewhere else in the meantime -- another tab -- the save is refused and you choose
 * whose version to keep, rather than one silently overwriting the other.
 *
 * Mount it with a key per document: everything here (the draft, undo history, selection) belongs to one.
 *
 * Read-only (a project shared with the user to view), layers can be picked -- the panels then show their properties,
 * disabled -- and the view zoomed and panned, but nothing can be changed, so nothing is ever saved.
 */
export function CanvasEditor<F>({
  projectId,
  noun,
  frame = SHOT_FRAME,
  document,
  imageUrls,
  persist,
  toolbarSlot,
  toolbar,
  fields,
  characters = [],
  props = [],
  registryLayers = false,
  undrawnUrl,
  placeholderLabel,
  locationName = "",
  progress = {},
  outOfDate = {},
  onGenerate,
  uploadsFillFrame = false,
  startWith,
  readOnly = false,
}: {
  projectId: string
  /** What the document is called in messages ("shot", "sketch") */
  noun: string
  /** Its frame's size (default: a shot's) */
  frame?: Frame
  /**
   * The latest copy of the document the page has. One that comes back newer while it's open is merged in when
   * `persist.mergeable` allows it.
   */
  document: Saved<F>
  /** A download URL for each image key in `document` */
  imageUrls: Record<string, string>
  persist: Persist<F>
  /** Where to draw undo/redo, the save status and `toolbar` -- the page's toolbar row (nothing is drawn until it exists) */
  toolbarSlot: HTMLElement | null
  /** The page's own toolbar buttons, after the save status */
  toolbar?: (actions: EditorActions) => ReactNode
  /** The panel under the layers for the document's own fields, if it has any */
  fields?: (
    fields: F,
    onEdit: (change: Partial<F>, field: string) => void
  ) => ReactNode
  characters?: Character[]
  props?: Prop[]
  /** Whether background, character and prop layers can be added (a shot's; never a sketch's) */
  registryLayers?: boolean
  /** The picture to show for a layer not drawn yet (what it will be drawn from), if any */
  undrawnUrl?: (layer: Layer) => string | null
  /** What a not-yet-drawn layer's placeholder says */
  placeholderLabel?: (layer: Layer) => string
  /** The name of the location a background shows */
  locationName?: string
  /** Where each layer stands with generation, by layer ID */
  progress?: Record<string, LayerProgress>
  /** The document's out-of-date layers (as last saved), with what changed, by layer ID */
  outOfDate?: Record<string, string[]>
  /** Asks for layers to be drawn (all of them, or one) -- for a document that's generated */
  onGenerate?: (layerId?: string) => Promise<unknown>
  /** Whether an uploaded image starts fitted to the whole frame (a sketch's), rather than at a modest size */
  uploadsFillFrame?: boolean
  /** An image to add as a layer as soon as the editor opens */
  startWith?: File
  /** Looking only (see above) */
  readOnly?: boolean
}) {
  const [state, dispatch] = useReducer(
    editorReducer as (
      state: EditorState<F>,
      action: EditorAction<F>
    ) => EditorState<F>,
    document,
    initialState
  )
  const [status, setStatus] = useState<SaveStatus>("saved")
  const [problem, setProblem] = useState<string | null>(null)
  // The layers waiting on "Delete these layers?" (every delete asks first)
  const [confirmDelete, setConfirmDelete] = useState<string[] | null>(null)
  const [tool, setTool] = useState<Tool>("select")
  const [pen, setPen] = useState<Pen>({ colour: "#000000", width: 4 })
  const canvas = useRef<CanvasHandle>(null)
  const [view, setView] = useState<View>(FIT)
  const [fitScale, setFitScale] = useState(1)
  const [scaleLocked, setScaleLocked] = useState(readScaleLock)
  const lockScale = (locked: boolean) => {
    setScaleLocked(locked)
    writeScaleLock(locked)
  }

  // The URL each image is drawn from, kept for the whole session: the first one known for it wins. Every save brings
  // back a fresh signed URL for every image, and switching to it would make the canvas download (and blink) each image
  // again after every edit. Uploads start with a URL for the file itself.
  const [knownUrls, setKnownUrls] = useState<Record<string, string>>(() => ({
    ...imageUrls,
  }))
  const learnUrls = (urls: Record<string, string>) =>
    setKnownUrls((known) => ({ ...urls, ...known }))

  // When the document comes back from elsewhere with a newer version that's safe to take in -- a shot's worker saving
  // an image, or the deck saving a reorder -- merge it in, so the next save isn't refused as a conflict
  const [seenVersion, setSeenVersion] = useState(document.version)
  if (document.version !== seenVersion) {
    setSeenVersion(document.version)
    if (
      document.version > state.baseline.version &&
      persist.mergeable?.(state.baseline, document)
    ) {
      dispatch({ type: "merge", saved: document })
      learnUrls(imageUrls)
    }
  }
  const latest = useRef(state)
  const saving = useRef(false)
  const failedDraft = useRef<Draft<F> | null>(null)
  const dirty = isDirty(state)

  // What the callbacks below read, kept current on every render -- so `save` itself never changes, and the effects
  // that depend on it don't re-run
  const persistRef = useRef(persist)
  const conflicted = useRef(false)
  useEffect(() => {
    latest.current = state
    persistRef.current = persist
    conflicted.current = status === "conflict"
  })

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
    const { save: send, fetch, mergeable } = persistRef.current
    try {
      for (let attempt = 1; ; attempt++) {
        try {
          const loaded = await send(current.draft, current.baseline.version)
          dispatch({ type: "saved", saved: loaded.saved })
          learnUrls(loaded.imageUrls)
          setStatus("saved")
          setProblem(null)
          failedDraft.current = null
          return true
        } catch (error) {
          // Refused because of a change that's safe to take in (generation saved an image meanwhile): merge it, and
          // save again on top of it
          if (
            error instanceof ApiError &&
            error.status === 409 &&
            mergeable &&
            attempt < 3
          ) {
            const newer = await fetch()
            if (mergeable(current.baseline, newer.saved)) {
              dispatch({ type: "merge", saved: newer.saved })
              learnUrls(newer.imageUrls)
              current = editorReducer(current, {
                type: "merge",
                saved: newer.saved,
              })
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
  }, [])

  /** Asks for layers to be drawn -- once the server has them all, saving first */
  const generate = async (layerId?: string) => {
    if (!onGenerate) {
      return
    }
    while (saving.current) {
      await new Promise((resolve) => setTimeout(resolve, 100)) // A save is already on its way
    }
    if (!(await save())) {
      return
    }
    try {
      await onGenerate(layerId)
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  /** Saves what's pending (waiting for a save already on its way), then hands back whether it's all saved */
  const saveNow = async () => {
    while (saving.current) {
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    return save()
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

  // Leaving (for another document, or another page) saves what's pending -- unless it's waiting on a conflict, or
  // already failed; leaving the site with unsaved changes asks first
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
    (
      change: (draft: Draft<F>) => Draft<F>,
      mergeKey?: string,
      select?: string[]
    ) => {
      if (!readOnly) {
        dispatch({ type: "edit", change, mergeKey, select })
      }
    },
    [readOnly]
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

  const editFields = (change: Partial<F>, field: string) =>
    edit(
      (draft) => ({ ...draft, fields: { ...draft.fields, ...change } }),
      `fields:${field}`
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

  /** A finished brush or eraser stroke: into its drawing, or a new one -- unless the document can't hold any more */
  const stroke = (target: string | null, finished: Stroke) => {
    if (
      strokePoints(state.draft.layers) + finished.points.length / 2 >
      MAX_STROKE_POINTS
    ) {
      setProblem(
        `This ${noun} can't hold any more drawing -- simplify or delete some strokes (or a drawing) first.`
      )
      return
    }
    if (target === null) {
      add({
        ...(newFreehandLayer(frame) as FreehandLayer),
        strokes: [finished],
      })
    } else {
      editLayers((layers) =>
        updateLayer(layers, target, (l) =>
          l.type === "freehand"
            ? { ...l, strokes: [...l.strokes, finished] }
            : l
        )
      )
    }
  }

  const warpStrokes = (id: string, strokes: Stroke[]) =>
    editLayers((layers) =>
      updateLayer(layers, id, (l) =>
        l.type === "freehand" ? { ...l, strokes } : l
      )
    )

  /** Uploads an image, then hands back its key and size -- showing any problem instead */
  const upload = async (
    file: File
  ): Promise<{ key: string; width: number; height: number } | null> => {
    setProblem(null)
    try {
      const [key, size] = await Promise.all([
        uploadImage(projectId, file),
        imageSize(file),
      ])
      learnUrls({ [key]: URL.createObjectURL(file) })
      return { key, ...size }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
      return null
    }
  }

  const addImage = async (file: File) => {
    const uploaded = await upload(file)
    if (uploaded) {
      const { width, height } = frame
      const scale = uploadsFillFrame
        ? Math.min(width / uploaded.width, height / uploaded.height)
        : Math.min(1, UPLOAD_FIT / Math.max(uploaded.width, uploaded.height))
      const layer = newImageLayer(
        uploaded.key,
        file.name.replace(/\.[^.]+$/, "").slice(0, 100),
        frame
      )
      add({
        ...layer,
        transform: { ...layer.transform, scale_x: scale, scale_y: scale },
      })
    }
  }

  // The image it was opened with goes in once (a ref, so a remount in development doesn't add it twice)
  const started = useRef(false)
  useEffect(() => {
    if (startWith && !readOnly && !started.current) {
      started.current = true
      void addImage(startWith)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only ever on opening
  }, [])

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

  // Keyboard: undo/redo, save now, zoom (Ctrl and =, - or 0), delete, V, D, B and E for the tools, and Escape to go
  // back to Select or else deselect -- but not while typing in a field
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
      // Read-only, only zooming and Escape (deselect) do anything
      const zooming = mod && ["=", "+", "-", "0"].includes(event.key)
      if (readOnly && !zooming && event.key !== "Escape") {
        return
      }
      if (mod && event.key.toLowerCase() === "z") {
        event.preventDefault()
        dispatch({ type: event.shiftKey ? "redo" : "undo" })
      } else if (mod && event.key.toLowerCase() === "y") {
        event.preventDefault()
        dispatch({ type: "redo" })
      } else if (mod && (event.key === "=" || event.key === "+")) {
        event.preventDefault() // The browser's own zoom otherwise
        setView((current) => zoomAt(current, current.zoom * ZOOM_STEP))
      } else if (mod && event.key === "-") {
        event.preventDefault()
        setView((current) => zoomAt(current, current.zoom / ZOOM_STEP))
      } else if (mod && event.key === "0") {
        event.preventDefault()
        setView(FIT)
      } else if (event.key === "Escape") {
        if (tool !== "select") {
          setTool("select")
        } else {
          dispatch({ type: "select", ids: [] })
        }
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "v") {
        setTool("select")
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "d") {
        setTool("distort")
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "b") {
        setTool("brush")
      } else if (!mod && !event.altKey && event.key.toLowerCase() === "e") {
        setTool("eraser")
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
      const newest = await persistRef.current.fetch()
      learnUrls(newest.imageUrls)
      if (keep === "theirs") {
        dispatch({ type: "load", saved: newest.saved })
        setStatus("saved")
      } else {
        // Save this draft over their version: take the current version number, then save as usual
        dispatch({ type: "saved", saved: newest.saved })
        failedDraft.current = null
        setStatus("saved")
      }
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  const imageUrl = (layer: Layer): string | null =>
    "image" in layer && layer.image
      ? (knownUrls[layer.image] ?? null)
      : (undrawnUrl?.(layer) ?? null)

  const actions: EditorActions = {
    dirty,
    save: saveNow,
    generate,
    flatten: () => {
      if (!canvas.current) {
        return Promise.reject(new Error("The canvas isn't ready yet."))
      }
      return canvas.current.flatten()
    },
    setProblem,
  }

  const toolbarRow = readOnly ? (
    <>
      <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <EyeIcon className="size-4" />
        View only
      </span>
      <ZoomBar view={view} fitScale={fitScale} onView={setView} />
      {toolbar && <PageToolbar render={toolbar} actions={actions} />}
    </>
  ) : (
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
      <ZoomBar view={view} fitScale={fitScale} onView={setView} />
      <SaveIndicator status={status} dirty={dirty} onSave={() => void save()} />
      {toolbar && <PageToolbar render={toolbar} actions={actions} />}
    </>
  )

  return (
    <div className="flex min-h-0 flex-1">
      {toolbarSlot && createPortal(toolbarRow, toolbarSlot)}
      <aside
        className="flex w-80 shrink-0 border-r"
        aria-label="Tools and layers"
      >
        <ToolStrip tool={tool} onTool={setTool} readOnly={readOnly} />
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            <LayersPanel
              layers={state.draft.layers}
              selection={selection}
              characters={characters}
              props={props}
              registryLayers={registryLayers}
              outOfDate={outOfDate}
              readOnly={readOnly}
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
              onAddText={() => add(newTextLayer(frame))}
              onAddGroup={() => add(newGroupLayer(frame))}
              onAddDrawing={() => add(newFreehandLayer(frame))}
              onAddImage={(file) => void addImage(file)}
              onAddCharacter={(character) => add(newCharacterLayer(character))}
              onAddProp={(prop) => add(newPropLayer(prop))}
            />
          </div>
          {fields && (
            <fieldset
              disabled={readOnly}
              className="min-h-0 min-w-0 flex-1 overflow-y-auto border-t p-3"
            >
              {fields(state.draft.fields, editFields)}
            </fieldset>
          )}
        </div>
      </aside>

      <section
        className="flex min-w-0 flex-1 flex-col gap-2 p-2"
        aria-label="Canvas"
      >
        {status === "conflict" && (
          <Alert variant="destructive">
            <TriangleAlertIcon />
            <AlertTitle>This {noun} was changed somewhere else</AlertTitle>
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
            ref={canvas}
            frame={frame}
            layers={state.draft.layers}
            selection={selection}
            tool={tool}
            pen={pen}
            imageUrl={imageUrl}
            placeholderLabel={placeholderLabel ?? ((layer) => layer.name)}
            onSelect={(ids) => dispatch({ type: "select", ids })}
            onTransform={applyTransforms}
            onWarp={warp}
            onWarpStrokes={warpStrokes}
            onStroke={stroke}
            view={view}
            onView={setView}
            onFitScale={setFitScale}
            scaleLocked={scaleLocked}
            readOnly={readOnly}
          />
          {tool === "distort" && (
            <p className="pointer-events-none absolute top-1 left-1/2 -translate-x-1/2 rounded-full border bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow-sm">
              Distort: drag a selected picture's or drawing's corners. Esc or V
              to go back to Select.
            </p>
          )}
          {(tool === "brush" || tool === "eraser") && (
            <PenBar
              tool={tool}
              pen={pen}
              onPen={setPen}
              hasDrawing={selected?.type === "freehand"}
            />
          )}
        </div>
      </section>

      <fieldset
        disabled={readOnly}
        className="w-80 min-w-0 shrink-0 overflow-y-auto border-l p-4"
        aria-label="Layer details"
      >
        <LayerProperties
          selected={selected}
          selectionCount={selection.length}
          characters={characters}
          props={props}
          locationName={locationName}
          onEditLayer={editSelected}
          onReplaceImage={(file) => void replaceImage(file)}
          onDistort={() => setTool("distort")}
          progress={selected ? progress[selected.id] : undefined}
          freshness={selected ? freshness(selected, outOfDate) : null}
          unsaved={dirty}
          scaleLocked={scaleLocked}
          onScaleLocked={lockScale}
          onGenerate={(layerId) => void generate(layerId)}
          readOnly={readOnly}
        />
      </fieldset>

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
 * The page's own toolbar buttons, given what they can ask the editor to do. A component (rather than calling `render`
 * while rendering the editor), as the actions are only ever called from its buttons' handlers.
 */
function PageToolbar({
  render,
  actions,
}: {
  render: (actions: EditorActions) => ReactNode
  actions: EditorActions
}) {
  return render(actions)
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
