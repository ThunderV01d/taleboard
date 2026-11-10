import { describe, expect, it } from "vitest"

import {
  finishStroke,
  strokeBounds,
  strokePoints,
  warpStrokes,
  type Stroke,
} from "@/lib/freehand"
import type { Layer } from "@/lib/layers"
import { UNWARPED } from "@/lib/warp"

function stroke(points: number[]): Stroke {
  return { points, colour: "#000000", width: 4, erase: false }
}

function freehand(id: string, ...strokes: Stroke[]): Layer {
  return {
    id,
    name: "Drawing",
    transform: {
      x: 512,
      y: 512,
      scale_x: 1,
      scale_y: 1,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
    },
    opacity: 1,
    visible: true,
    type: "freehand",
    strokes,
  }
}

describe("finishStroke", () => {
  it("drops the points of a straight run, keeping its ends", () => {
    expect(finishStroke([0, 0, 1, 0, 2, 0, 3, 0, 10, 0])).toEqual([0, 0, 10, 0])
  })

  it("keeps the points where the path bends", () => {
    expect(finishStroke([0, 0, 5, 0, 10, 0, 10, 5, 10, 10])).toEqual([
      0, 0, 10, 0, 10, 10,
    ])
  })

  it("rounds to a tenth of a pixel", () => {
    expect(finishStroke([0.123, 0.456, 10.987, 3.21])).toEqual([
      0.1, 0.5, 11, 3.2,
    ])
  })

  it("turns a tap into a dot", () => {
    expect(finishStroke([4, 5])).toEqual([4, 5, 4, 5])
  })

  it("leaves nothing for an empty path", () => {
    expect(finishStroke([])).toEqual([])
  })
})

describe("strokePoints", () => {
  it("counts every stroke's points, inside groups too", () => {
    const layers: Layer[] = [
      freehand("a", stroke([0, 0, 1, 1]), stroke([0, 0, 1, 1, 2, 2])),
      {
        ...freehand("g"),
        type: "group",
        children: [freehand("b", stroke([0, 0, 1, 1]))],
      } as unknown as Layer,
    ]

    expect(strokePoints(layers)).toBe(7)
  })
})

describe("strokeBounds", () => {
  it("boxes every stroke", () => {
    expect(
      strokeBounds([stroke([0, 10, 20, 30]), stroke([-5, 0, 5, 5])])
    ).toEqual({ x: -5, y: 0, width: 25, height: 30 })
  })

  it("leaves out the erasing strokes", () => {
    expect(
      strokeBounds([
        stroke([0, 0, 10, 10]),
        { ...stroke([-50, -50, 50, 50]), erase: true },
      ])
    ).toEqual({ x: 0, y: 0, width: 10, height: 10 })
  })

  it("gives a flat line a box with some height, and nothing drawn none", () => {
    expect(strokeBounds([stroke([0, 0, 10, 0])])?.height).toBe(1)
    expect(strokeBounds([])).toBeNull()
  })
})

describe("warpStrokes", () => {
  const bounds = { x: 0, y: 0, width: 100, height: 100 }

  it("leaves a drawing as it was with the corners where they started", () => {
    const strokes = [stroke([0, 0, 50, 50, 100, 100])]

    expect(warpStrokes(strokes, bounds, UNWARPED)).toEqual(strokes)
  })

  it("takes every point along with the corners, keeping each stroke's pen", () => {
    const doubled = {
      top_left: { x: 0, y: 0 },
      top_right: { x: 2, y: 0 },
      bottom_right: { x: 2, y: 1 },
      bottom_left: { x: 0, y: 1 },
    }
    const strokes = [{ ...stroke([0, 0, 50, 50, 100, 100]), width: 9 }]

    const [warped] = warpStrokes(strokes, bounds, doubled)

    expect(warped.points).toEqual([0, 0, 100, 50, 200, 100])
    expect(warped.width).toBe(9)
  })
})
