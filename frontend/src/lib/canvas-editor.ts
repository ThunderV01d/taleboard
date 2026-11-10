/**
 * The canvas editor's state: the document being edited (a shot, or a sketch), its undo history, and what's selected.
 *
 * Every edit makes a new draft (the layer functions in lib/layers.ts never change a list in place), so undo is just
 * going back to the previous draft. The baseline is the document as last saved -- the draft is "dirty" while it
 * differs.
 *
 * Generation saves images into a shot on the server while it's open here. Such a save changes nothing but layers'
 * images and what they were drawn from, so it's merged in -- into the draft and its whole undo history, so undoing
 * never takes a drawn image away -- rather than treated as someone else's edit.
 */
import type { Layer } from "@/lib/layers"

/**
 * Everything a save sends (apart from the version): the layers, and the document's own fields edited alongside them
 * (a shot's framing -- a sketch has none).
 */
export type Draft<F = unknown> = { fields: F; layers: Layer[] }

/** A document as it was last saved (or loaded): its content, and the version the next save sends */
export type Saved<F = unknown> = { version: number; draft: Draft<F> }

/** Undo goes back at most this many edits */
const HISTORY_LIMIT = 100

export type EditorState<F = unknown> = {
  /** The document as last saved (or loaded) -- its version is what the next save sends */
  baseline: Saved<F>
  draft: Draft<F>
  past: Draft<F>[]
  future: Draft<F>[]
  /** Selected layer IDs, in the order they were picked */
  selection: string[]
  /**
   * The key of the last edit that can absorb the next one, so typing into a field is one undo step rather than one
   * per keystroke.
   */
  mergeKey: string | null
}

export type EditorAction<F = unknown> =
  | {
      type: "edit"
      change: (draft: Draft<F>) => Draft<F>
      mergeKey?: string
      select?: string[]
    }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "select"; ids: string[] }
  | { type: "saved"; saved: Saved<F> }
  | { type: "load"; saved: Saved<F> }
  | { type: "merge"; saved: Saved<F> }

/**
 * The editor's starting state for a document.
 */
export function initialState<F>(saved: Saved<F>): EditorState<F> {
  return {
    baseline: saved,
    draft: saved.draft,
    past: [],
    future: [],
    selection: [],
    mergeKey: null,
  }
}

/**
 * True when two drafts hold the same content. Key order doesn't count: the API sends fields back in its own order,
 * which needn't match the order the editor built them in.
 */
export function sameDraft<F>(a: Draft<F>, b: Draft<F>): boolean {
  return canonical(a) === canonical(b)
}

/** JSON with every object's keys sorted */
function canonical(value: unknown): string {
  return JSON.stringify(value, (_, v: unknown) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        )
      : v
  )
}

/**
 * True while the draft differs from what was last saved.
 */
export function isDirty<F>(state: EditorState<F>): boolean {
  return !sameDraft(state.draft, state.baseline.draft)
}

/** Selected IDs that still exist (an undo can remove a layer that was selected) */
function stillThere<F>(selection: string[], draft: Draft<F>): string[] {
  const ids = new Set<string>()
  const walk = (layers: Layer[]) =>
    layers.forEach((layer) => {
      ids.add(layer.id)
      if (layer.type === "group") {
        walk(layer.children)
      }
    })
  walk(draft.layers)
  return selection.filter((id) => ids.has(id))
}

/** The two fields generation writes into a layer */
type Drawn = Pick<
  Extract<Layer, { type: "background" | "character" | "prop" }>,
  "image" | "last_generated_params"
>

function isGenerated(
  layer: Layer
): layer is Extract<Layer, { type: "background" | "character" | "prop" }> {
  return (
    layer.type === "background" ||
    layer.type === "character" ||
    layer.type === "prop"
  )
}

/** A layer tree with what generation writes taken out -- so two trees can be compared apart from it */
function withoutDrawn(layers: Layer[]): Layer[] {
  return layers.map((layer) => {
    if (layer.type === "group") {
      return { ...layer, children: withoutDrawn(layer.children) }
    }
    if (isGenerated(layer)) {
      return { ...layer, image: null, last_generated_params: null }
    }
    return layer
  })
}

/**
 * True when a newer copy of a shot differs from the one it was loaded as only in what generation writes (layers'
 * images and the params they were drawn from) -- the worker's save, not someone's edit.
 */
export function onlyDrawnSince<F>(
  baseline: Saved<F>,
  newer: Saved<F>
): boolean {
  const before = baseline.draft
  const after = newer.draft
  return sameDraft(
    { ...before, layers: withoutDrawn(before.layers) },
    { ...after, layers: withoutDrawn(after.layers) }
  )
}

/** What generation changed between two copies of a shot: each changed layer's new image and params, by layer ID */
function drawnSince<F>(
  baseline: Saved<F>,
  newer: Saved<F>
): Map<string, Drawn> {
  const before = new Map<string, string>()
  const walk = (layers: Layer[], visit: (layer: Layer) => void) =>
    layers.forEach((layer) => {
      visit(layer)
      if (layer.type === "group") {
        walk(layer.children, visit)
      }
    })
  walk(baseline.draft.layers, (layer) => {
    if (isGenerated(layer)) {
      before.set(
        layer.id,
        canonical([layer.image, layer.last_generated_params])
      )
    }
  })
  const changed = new Map<string, Drawn>()
  walk(newer.draft.layers, (layer) => {
    if (
      isGenerated(layer) &&
      canonical([layer.image, layer.last_generated_params]) !==
        before.get(layer.id)
    ) {
      changed.set(layer.id, {
        image: layer.image,
        last_generated_params: layer.last_generated_params,
      } as Drawn)
    }
  })
  return changed
}

/** A draft with these layers' images and params replaced (wherever the layers are now, if they still exist) */
function withDrawn<F>(draft: Draft<F>, drawn: Map<string, Drawn>): Draft<F> {
  if (drawn.size === 0) {
    return draft
  }
  const patch = (layers: Layer[]): Layer[] =>
    layers.map((layer) => {
      if (layer.type === "group") {
        return { ...layer, children: patch(layer.children) }
      }
      const update = drawn.get(layer.id)
      return update && isGenerated(layer)
        ? ({ ...layer, ...update } as Layer)
        : layer
    })
  return { ...draft, layers: patch(draft.layers) }
}

export function editorReducer<F>(
  state: EditorState<F>,
  action: EditorAction<F>
): EditorState<F> {
  switch (action.type) {
    case "edit": {
      const draft = action.change(state.draft)
      if (draft === state.draft) {
        return state
      }
      const merging =
        action.mergeKey !== undefined && action.mergeKey === state.mergeKey
      return {
        ...state,
        draft,
        past: merging
          ? state.past
          : [...state.past, state.draft].slice(-HISTORY_LIMIT),
        future: [],
        selection: action.select ?? stillThere(state.selection, draft),
        mergeKey: action.mergeKey ?? null,
      }
    }
    case "undo": {
      const previous = state.past.at(-1)
      if (!previous) {
        return state
      }
      return {
        ...state,
        draft: previous,
        past: state.past.slice(0, -1),
        future: [state.draft, ...state.future],
        selection: stillThere(state.selection, previous),
        mergeKey: null,
      }
    }
    case "redo": {
      const next = state.future[0]
      if (!next) {
        return state
      }
      return {
        ...state,
        draft: next,
        past: [...state.past, state.draft],
        future: state.future.slice(1),
        selection: stillThere(state.selection, next),
        mergeKey: null,
      }
    }
    case "select":
      return { ...state, selection: action.ids, mergeKey: null }
    case "saved":
      // The draft stays as it is -- if it was edited while the save was in flight, it's simply still dirty
      return { ...state, baseline: action.saved }
    case "load":
      return {
        ...initialState(action.saved),
        selection: stillThere(state.selection, action.saved.draft),
      }
    case "merge": {
      // Only generation's changes come across; everything else in the draft (and its history) is the user's
      const drawn = drawnSince(state.baseline, action.saved)
      return {
        ...state,
        baseline: action.saved,
        draft: withDrawn(state.draft, drawn),
        past: state.past.map((draft) => withDrawn(draft, drawn)),
        future: state.future.map((draft) => withDrawn(draft, drawn)),
      }
    }
  }
}
