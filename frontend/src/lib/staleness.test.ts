/**
 * Unit tests for what the editor shows about out-of-date layers (lib/staleness.ts).
 *
 * Run with: npm test
 */
import { describe, expect, it } from "vitest"

import { newBackgroundLayer, newTextLayer, type Layer } from "@/lib/layers"
import type { Shot } from "@/lib/shots"
import { changesText, freshness, shotFreshness } from "@/lib/staleness"

const drawn = (layer: Layer) => ({ ...layer, image: "plate.png" }) as Layer

describe("freshness", () => {
  const background = drawn(newBackgroundLayer())

  it("is up to date when the shot doesn't list it, and out of date with what changed when it does", () => {
    expect(freshness(background, {})).toEqual({ state: "current" })
    expect(freshness(background, { [background.id]: ["shot_size"] })).toEqual({
      state: "stale",
      changes: ["shot_size"],
    })
  })

  it("is undrawn when listed with nothing changed, or with no image at all (added since the save)", () => {
    expect(freshness(background, { [background.id]: [] })).toEqual({
      state: "undrawn",
    })
    expect(freshness(newBackgroundLayer(), {})).toEqual({ state: "undrawn" })
  })

  it("is nothing for a layer that isn't generated", () => {
    expect(freshness(newTextLayer(), {})).toBeNull()
  })
})

describe("changesText", () => {
  it("names what changed, in words", () => {
    expect(changesText(["action"])).toBe("the action")
    expect(changesText(["orientation", "description", "sketches"])).toBe(
      "which way it faces, the description and a sketch"
    )
  })

  it("falls back to the param's own name for one it doesn't know", () => {
    expect(changesText(["new_thing"])).toBe("new thing")
  })
})

describe("shotFreshness", () => {
  it("counts the out-of-date layers apart from the undrawn ones", () => {
    const shot = { out_of_date: { a: ["action"], b: [], c: ["facing"] } }

    expect(shotFreshness(shot as unknown as Shot)).toEqual({
      stale: 2,
      undrawn: 1,
    })
  })
})
