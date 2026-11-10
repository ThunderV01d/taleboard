/**
 * Unit tests for the canvas editor's zoom and pan (lib/zoom.ts).
 *
 * Run with: npm test
 */
import { describe, expect, it } from "vitest"

import { clampPan, FIT, MAX_ZOOM, MIN_ZOOM, zoomAt } from "@/lib/zoom"

describe("zoomAt", () => {
  it("zooms about the middle by default, scaling the pan with it", () => {
    expect(zoomAt({ zoom: 1, x: 10, y: -20 }, 2)).toEqual({
      zoom: 2,
      x: 20,
      y: -40,
    })
  })

  it("keeps the point it zooms about where it is on screen", () => {
    const view = { zoom: 2, x: 30, y: 0 }
    const point = { x: 100, y: 50 }
    const zoomed = zoomAt(view, 4, point)

    // A frame point d from the frame's centre is on screen at pan + d * zoom (times the fit scale) -- the same d stays put
    const d = {
      x: (point.x - view.x) / view.zoom,
      y: (point.y - view.y) / view.zoom,
    }
    expect(zoomed.x + d.x * zoomed.zoom).toBeCloseTo(point.x)
    expect(zoomed.y + d.y * zoomed.zoom).toBeCloseTo(point.y)
  })

  it("stays within its limits", () => {
    expect(zoomAt(FIT, 1000).zoom).toBe(MAX_ZOOM)
    expect(zoomAt(FIT, 0.01).zoom).toBe(MIN_ZOOM)
  })
})

describe("clampPan", () => {
  const space = { width: 800, height: 600 }

  it("lets the frame move off the space only until a strip of it is left", () => {
    const frame = { width: 2000, height: 2000 }
    expect(clampPan({ zoom: 4, x: 5000, y: -5000 }, frame, space)).toEqual({
      zoom: 4,
      x: 1400 - 48,
      y: -(1300 - 48),
    })
  })

  it("leaves a pan within reach as it is", () => {
    const view = { zoom: 2, x: 100, y: -100 }
    expect(clampPan(view, { width: 1200, height: 1200 }, space)).toEqual(view)
  })
})
