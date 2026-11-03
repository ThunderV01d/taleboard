/**
 * Unit tests for the canvas editor's state (lib/shot-editor.ts): undo and redo, merging typing into one step,
 * selection, and when the draft counts as unsaved.
 *
 * Run with: npm test
 */
import { describe, expect, it } from "vitest"

import { newTextLayer, removeLayers, type Layer } from "@/lib/layers"
import {
  onlyDrawnSince,
  editorReducer,
  initialState,
  isDirty,
  toSaveBody,
  type Draft,
  type EditorState,
} from "@/lib/shot-editor"
import type { Shot } from "@/lib/shots"

function shot(layers: Layer[] = [], version = 0): Shot {
  return {
    id: "shot",
    scene_id: "scene",
    order: 0,
    description: "",
    duration_s: 2,
    shot_size: "medium",
    angle: "eye_level",
    details: "",
    layers,
    version,
    image_urls: {},
  }
}

const rename =
  (name: string) =>
  (draft: Draft): Draft => ({
    ...draft,
    fields: { ...draft.fields, description: name },
  })

function run(
  state: EditorState,
  ...actions: Parameters<typeof editorReducer>[1][]
) {
  return actions.reduce(editorReducer, state)
}

describe("the canvas editor's state", () => {
  it("starts clean, and is dirty once edited", () => {
    const start = initialState(shot())
    expect(isDirty(start)).toBe(false)
    expect(isDirty(run(start, { type: "edit", change: rename("a") }))).toBe(
      true
    )
  })

  it("undoes and redoes edits in order", () => {
    const state = run(
      initialState(shot()),
      { type: "edit", change: rename("a") },
      { type: "edit", change: rename("b") },
      { type: "undo" }
    )
    expect(state.draft.fields.description).toBe("a")
    expect(run(state, { type: "undo" }).draft.fields.description).toBe("")
    expect(run(state, { type: "redo" }).draft.fields.description).toBe("b")
  })

  it("is clean again after undoing back to the saved version", () => {
    const state = run(
      initialState(shot()),
      { type: "edit", change: rename("a") },
      { type: "undo" }
    )
    expect(isDirty(state)).toBe(false)
  })

  it("forgets the redo trail once something new is edited", () => {
    const state = run(
      initialState(shot()),
      { type: "edit", change: rename("a") },
      { type: "undo" },
      { type: "edit", change: rename("c") },
      { type: "redo" }
    )
    expect(state.draft.fields.description).toBe("c")
  })

  it("merges edits with the same key into one undo step", () => {
    const typed = run(
      initialState(shot()),
      { type: "edit", change: rename("h"), mergeKey: "description" },
      { type: "edit", change: rename("hi"), mergeKey: "description" },
      { type: "edit", change: rename("hi!"), mergeKey: "description" }
    )
    expect(typed.past).toHaveLength(1)
    expect(run(typed, { type: "undo" }).draft.fields.description).toBe("")
  })

  it("starts a new undo step after a different edit, or a selection", () => {
    const state = run(
      initialState(shot()),
      { type: "edit", change: rename("a"), mergeKey: "description" },
      { type: "select", ids: [] },
      { type: "edit", change: rename("ab"), mergeKey: "description" }
    )
    expect(state.past).toHaveLength(2)
  })

  it("ignores edits that change nothing", () => {
    const start = initialState(shot())
    expect(run(start, { type: "edit", change: (draft) => draft })).toBe(start)
  })

  it("drops removed layers from the selection, including after an undo", () => {
    const text = newTextLayer()
    const withText = run(initialState(shot()), {
      type: "edit",
      change: (d) => ({ ...d, layers: [text] }),
      select: [text.id],
    })
    expect(withText.selection).toEqual([text.id])
    const removed = run(withText, {
      type: "edit",
      change: (d) => ({ ...d, layers: removeLayers(d.layers, [text.id]) }),
    })
    expect(removed.selection).toEqual([])
    expect(run(withText, { type: "undo" }).selection).toEqual([])
  })

  it("keeps the draft after a save, and saves over the new version next time", () => {
    const edited = run(initialState(shot()), {
      type: "edit",
      change: rename("a"),
    })
    const saved = run(edited, {
      type: "saved",
      shot: { ...shot(), description: "a", version: 1 },
    })

    expect(saved.draft).toBe(edited.draft)
    expect(isDirty(saved)).toBe(false)
    expect(toSaveBody(saved).version).toBe(1)
  })

  it("stays dirty when edited while a save was in flight", () => {
    const sent = run(initialState(shot()), {
      type: "edit",
      change: rename("a"),
    })
    const editedMeanwhile = run(sent, { type: "edit", change: rename("ab") })
    const saved = run(editedMeanwhile, {
      type: "saved",
      shot: { ...shot(), description: "a", version: 1 },
    })

    expect(isDirty(saved)).toBe(true)
  })

  it("is clean after a save that sends the layers back with their fields in another order", () => {
    const layer = newTextLayer()
    const edited = run(initialState(shot()), {
      type: "edit",
      change: (draft) => ({ ...draft, layers: [layer] }),
    })
    // As the API returns it: the same values, keys in its own order
    const { transform, ...rest } = layer
    const reordered = {
      transform: Object.fromEntries(Object.entries(transform).reverse()),
      ...rest,
    } as Layer
    const saved = run(edited, {
      type: "saved",
      shot: shot([reordered], 1),
    })

    expect(isDirty(saved)).toBe(false)
  })

  it("loads a fresh copy, dropping the draft and history", () => {
    const edited = run(initialState(shot()), {
      type: "edit",
      change: rename("a"),
    })
    const loaded = run(edited, { type: "load", shot: shot([], 5) })

    expect([
      loaded.draft.fields.description,
      loaded.past.length,
      loaded.baseline.version,
    ]).toEqual(["", 0, 5])
  })
})

describe("merging what generation drew", () => {
  const background = (image: string | null): Layer =>
    ({
      ...newTextLayer(),
      type: "background",
      id: "bg",
      name: "Background",
      facing: "north",
      image,
      corners: null,
      last_generated_params: image ? ({ facing: "north" } as never) : null,
    }) as unknown as Layer

  it("tells a generation save from someone's edit", () => {
    const loaded = shot([background(null)], 1)
    const drawn = shot([background("plates/north.png")], 2)
    const edited = { ...drawn, description: "someone else's edit" }

    expect(onlyDrawnSince(loaded, drawn)).toBe(true)
    expect(onlyDrawnSince(loaded, edited)).toBe(false)
  })

  it("brings the image into the draft, keeps the user's edits, and saves over the new version", () => {
    const loaded = shot([background(null)], 1)
    const edited = run(initialState(loaded), {
      type: "edit",
      change: rename("typed while it was being drawn"),
    })

    const merged = run(edited, {
      type: "merge",
      shot: shot([background("plates/north.png")], 2),
    })

    expect((merged.draft.layers[0] as { image: string }).image).toBe(
      "plates/north.png"
    )
    expect(merged.draft.fields.description).toBe(
      "typed while it was being drawn"
    )
    expect(isDirty(merged)).toBe(true)
    expect(toSaveBody(merged).version).toBe(2)
  })

  it("puts the image into the undo history too, so undoing never takes it away", () => {
    const loaded = shot([background(null)], 1)
    const edited = run(
      initialState(loaded),
      { type: "edit", change: rename("a") },
      { type: "edit", change: rename("ab") }
    )

    const merged = run(edited, {
      type: "merge",
      shot: shot([background("plates/north.png")], 2),
    })
    const undone = run(merged, { type: "undo" }, { type: "undo" })

    expect((undone.draft.layers[0] as { image: string }).image).toBe(
      "plates/north.png"
    )
    expect(isDirty(undone)).toBe(false)
  })

  it("leaves a layer deleted meanwhile deleted", () => {
    const loaded = shot([background(null)], 1)
    const deleted = run(initialState(loaded), {
      type: "edit",
      change: (draft) => ({ ...draft, layers: [] }),
    })

    const merged = run(deleted, {
      type: "merge",
      shot: shot([background("plates/north.png")], 2),
    })

    expect(merged.draft.layers).toEqual([])
  })
})
