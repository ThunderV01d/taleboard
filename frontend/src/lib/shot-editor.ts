/**
 * The canvas editor's state: the shot being edited, its undo history, and what's selected.
 *
 * Every edit makes a new draft (the layer functions in lib/layers.ts never change a list in place), so undo is just
 * going back to the previous draft. The baseline is the shot as last saved -- the draft is "dirty" while it differs.
 */
import type { Layer } from "@/lib/layers"
import type { Shot, ShotSave } from "@/lib/shots"

/** The shot fields edited alongside the layers */
export type ShotFields = Pick<
  Shot,
  "description" | "duration_s" | "shot_size" | "angle" | "details"
>

/** Everything a save sends (apart from the version) */
export type Draft = { fields: ShotFields; layers: Layer[] }

/** Undo goes back at most this many edits */
const HISTORY_LIMIT = 100

export type EditorState = {
  /** The shot as last saved (or loaded) -- its version is what the next save sends */
  baseline: Shot
  draft: Draft
  past: Draft[]
  future: Draft[]
  /** Selected layer IDs, in the order they were picked */
  selection: string[]
  /**
   * The key of the last edit that can absorb the next one, so typing into a field is one undo step rather than one
   * per keystroke.
   */
  mergeKey: string | null
}

export type EditorAction =
  | {
      type: "edit"
      change: (draft: Draft) => Draft
      mergeKey?: string
      select?: string[]
    }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "select"; ids: string[] }
  | { type: "saved"; shot: Shot }
  | { type: "load"; shot: Shot }

export function draftOf(shot: Shot): Draft {
  const { description, duration_s, shot_size, angle, details, layers } = shot
  return {
    fields: { description, duration_s, shot_size, angle, details },
    layers,
  }
}

/**
 * The editor's starting state for a shot.
 */
export function initialState(shot: Shot): EditorState {
  return {
    baseline: shot,
    draft: draftOf(shot),
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
export function sameDraft(a: Draft, b: Draft): boolean {
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
export function isDirty(state: EditorState): boolean {
  return !sameDraft(state.draft, draftOf(state.baseline))
}

/**
 * The request body that saves the draft over the baseline's version.
 */
export function toSaveBody(
  state: EditorState,
  version = state.baseline.version
): ShotSave {
  return { ...state.draft.fields, layers: state.draft.layers, version }
}

/** Selected IDs that still exist (an undo can remove a layer that was selected) */
function stillThere(selection: string[], draft: Draft): string[] {
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

export function editorReducer(
  state: EditorState,
  action: EditorAction
): EditorState {
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
      return { ...state, baseline: action.shot }
    case "load":
      return {
        ...initialState(action.shot),
        selection: stillThere(state.selection, draftOf(action.shot)),
      }
  }
}
