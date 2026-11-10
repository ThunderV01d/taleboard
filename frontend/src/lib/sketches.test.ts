/**
 * Unit tests for sketches as the canvas editor holds them (lib/sketches.ts).
 *
 * Run with: npm test
 */
import { describe, expect, it } from "vitest"

import { newTextLayer } from "@/lib/layers"
import { savedSketch, type Sketch } from "@/lib/sketches"

describe("savedSketch", () => {
  const start = [newTextLayer()]

  it("starts a new sketch at version 0 with the layers given, so the first save creates it", () => {
    expect(savedSketch(null, start)).toEqual({
      version: 0,
      draft: { fields: {}, layers: start },
    })
  })

  it("opens a saved sketch as it was saved, ignoring the starting layers", () => {
    const sketch = {
      registry: "characters",
      entry_id: "mara",
      slot: "left",
      width: 512,
      height: 1024,
      layers: [],
      version: 3,
      image_urls: {},
    } satisfies Sketch

    expect(savedSketch(sketch, start)).toEqual({
      version: 3,
      draft: { fields: {}, layers: [] },
    })
  })
})
