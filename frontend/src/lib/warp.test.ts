/**
 * Unit tests for the perspective warp maths (warp.ts): the corner checks, the square-to-corners mapping, and the
 * per-triangle transforms the canvas draws it with.
 */
import { describe, expect, it } from "vitest"

import {
  affineBetween,
  isConvex,
  isUnwarped,
  squareToQuad,
  UNWARPED,
  warpedBounds,
  type Corners,
  type Point,
} from "@/lib/warp"

/** A trapezium narrower at the top -- a wall seen from below */
const KEYSTONE: Corners = {
  top_left: { x: 0.2, y: 0 },
  top_right: { x: 0.8, y: 0 },
  bottom_right: { x: 1, y: 1 },
  bottom_left: { x: 0, y: 1 },
}

const close = (p: Point, q: Point) => {
  expect(p.x).toBeCloseTo(q.x, 9)
  expect(p.y).toBeCloseTo(q.y, 9)
}

describe("corners", () => {
  it("start where the picture's own corners are", () => {
    expect(isUnwarped(UNWARPED)).toBe(true)
    expect(isUnwarped(KEYSTONE)).toBe(false)
  })

  it("may make any convex shape, even past the picture's edges", () => {
    expect(isConvex(UNWARPED)).toBe(true)
    expect(isConvex(KEYSTONE)).toBe(true)
    expect(
      isConvex({
        ...UNWARPED,
        top_left: { x: -0.5, y: -0.5 },
        bottom_right: { x: 2, y: 1.5 },
      })
    ).toBe(true)
  })

  it.each([
    [
      "crossed over",
      { ...UNWARPED, top_left: { x: 1, y: 0 }, top_right: { x: 0, y: 0 } },
    ],
    [
      "pushed in past the diagonal",
      { ...UNWARPED, top_left: { x: 0.8, y: 0.8 } },
    ],
    [
      "flattened onto another corner",
      { ...UNWARPED, top_left: { x: 1, y: 0 } },
    ],
    [
      "mirrored",
      { ...UNWARPED, top_right: { x: 0, y: 1 }, bottom_left: { x: 1, y: 0 } },
    ],
    ["not numbers", { ...UNWARPED, top_left: { x: NaN, y: 0 } }],
  ])("may not fold the picture: %s", (_, corners) => {
    expect(isConvex(corners)).toBe(false)
  })

  it("can also be kept from getting close to a triangle", () => {
    // Bottom-left pulled almost onto the line from top-left to bottom-right: a corner of nearly 180 degrees
    const nearlyFlat = { ...UNWARPED, bottom_left: { x: 0.48, y: 0.52 } }

    expect(isConvex(nearlyFlat)).toBe(true)
    expect(isConvex(nearlyFlat, 10)).toBe(false)
    expect(isConvex(KEYSTONE, 10)).toBe(true)
  })
})

describe("mapping the picture onto its corners", () => {
  it("takes each corner of the picture to its corner", () => {
    const map = squareToQuad(KEYSTONE)

    close(map(0, 0), KEYSTONE.top_left)
    close(map(1, 0), KEYSTONE.top_right)
    close(map(1, 1), KEYSTONE.bottom_right)
    close(map(0, 1), KEYSTONE.bottom_left)
  })

  it("leaves an unwarped picture as it is", () => {
    close(squareToQuad(UNWARPED)(0.3, 0.7), { x: 0.3, y: 0.7 })
  })

  it("is a true perspective: the picture's middle goes where the diagonals cross, not to the corners' average", () => {
    // Diagonals of the keystone: (0.2, 0)-(1, 1) and (0.8, 0)-(0, 1) cross at (0.5, 0.375)
    close(squareToQuad(KEYSTONE)(0.5, 0.5), { x: 0.5, y: 0.375 })
  })

  it("keeps straight lines straight", () => {
    const map = squareToQuad(KEYSTONE)
    const [a, b, c] = [map(0.1, 0.2), map(0.5, 0.5), map(0.9, 0.8)]

    expect((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)).toBeCloseTo(
      0,
      9
    )
  })

  it("measures the warped picture's box in the picture's own size", () => {
    expect(
      warpedBounds({ ...UNWARPED, top_left: { x: -0.5, y: 0.25 } }, 200, 100)
    ).toEqual({ x: -100, y: 0, width: 300, height: 100 })
  })
})

describe("drawing it as triangles", () => {
  it("finds the transform that takes one triangle exactly onto another", () => {
    const from: [Point, Point, Point] = [
      { x: 0, y: 0 },
      { x: 10, y: 0 },
      { x: 10, y: 10 },
    ]
    const to: [Point, Point, Point] = [
      { x: 5, y: 3 },
      { x: 20, y: 8 },
      { x: 12, y: 30 },
    ]
    const [a, b, c, d, e, f] = affineBetween(from, to)

    from.forEach((p, i) =>
      close({ x: a * p.x + c * p.y + e, y: b * p.x + d * p.y + f }, to[i])
    )
  })
})
