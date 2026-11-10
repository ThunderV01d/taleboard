/**
 * Freehand drawing: turning a pen's path into a stroke worth keeping, the layer's own coordinates, and warping a
 * drawing with Distort.
 *
 * A freehand layer keeps vector strokes (flat x, y pairs in its own space, (0, 0) its centre) rather than pixels, so
 * each stroke is undoable on its own and a drawing can be moved, resized or warped without blurring. They're stored
 * inline in the shot (or sketch), so every stroke is simplified before it's kept, and a shot holds at most
 * MAX_STROKE_POINTS of them.
 */
import type { Layer } from "@/lib/layers"
import { squareToQuad, type Corners } from "@/lib/warp"

export type FreehandLayer = Extract<Layer, { type: "freehand" }>
export type Stroke = FreehandLayer["strokes"][number]

/** Must match the API's limit on stroke points in one shot or sketch (MAX_STROKE_POINTS) */
export const MAX_STROKE_POINTS = 20_000

/** How far (in the layer's pixels) a simplified stroke may stray from the path drawn -- below what the eye sees */
const SIMPLIFY_TOLERANCE = 0.75

/**
 * A pen's path made into a stroke's points: simplified (dropping points that barely bend it) and rounded to a tenth
 * of a pixel. A single tap becomes a dot -- the same point twice, which a round-capped line draws as one.
 *
 * @param points - The path, as flat x, y pairs, in the order drawn.
 * @returns The stroke's points.
 */
export function finishStroke(points: number[]): number[] {
  const pairs = toPairs(points)
  if (pairs.length === 0) {
    return []
  }
  const kept = pairs.length < 3 ? pairs : simplify(pairs, SIMPLIFY_TOLERANCE)
  const rounded = kept.flatMap(([x, y]) => [round(x), round(y)])
  return rounded.length === 2 ? [...rounded, ...rounded] : rounded
}

/**
 * How many stroke points (x, y pairs) a layer graph holds, groups included -- what MAX_STROKE_POINTS limits.
 */
export function strokePoints(layers: Layer[]): number {
  return layers.reduce(
    (total, layer) =>
      total +
      (layer.type === "freehand"
        ? layer.strokes.reduce((sum, s) => sum + s.points.length / 2, 0)
        : layer.type === "group"
          ? strokePoints(layer.children)
          : 0),
    0
  )
}

/** The box around a drawing's ink (its erasing strokes aren't part of it), in its own space -- null for a layer with nothing drawn */
export type Bounds = { x: number; y: number; width: number; height: number }

export function strokeBounds(strokes: Stroke[]): Bounds | null {
  const ink = strokes.filter((s) => !s.erase)
  const xs = ink.flatMap((s) => s.points.filter((_, i) => i % 2 === 0))
  const ys = ink.flatMap((s) => s.points.filter((_, i) => i % 2 === 1))
  if (xs.length === 0) {
    return null
  }
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  // A drawing that's a single straight line still gets a box Distort can pull on
  return {
    x,
    y,
    width: Math.max(Math.max(...xs) - x, 1),
    height: Math.max(Math.max(...ys) - y, 1),
  }
}

/**
 * A drawing warped by Distort: its box's corners moved to the given ones (fractions of the box, as a picture's are),
 * and every point of every stroke taken along by the same perspective transform. Widths stay as they were.
 *
 * @param strokes - The drawing's strokes.
 * @param bounds - The box the corners are fractions of (its strokes' bounds, before the drag).
 * @param corners - Where the box's corners have been dragged to.
 * @returns The warped strokes.
 */
export function warpStrokes(
  strokes: Stroke[],
  bounds: Bounds,
  corners: Corners
): Stroke[] {
  const toQuad = squareToQuad(corners)
  return strokes.map((stroke) => ({
    ...stroke,
    points: toPairs(stroke.points).flatMap(([x, y]) => {
      const p = toQuad(
        (x - bounds.x) / bounds.width,
        (y - bounds.y) / bounds.height
      )
      return [
        round(bounds.x + p.x * bounds.width),
        round(bounds.y + p.y * bounds.height),
      ]
    }),
  }))
}

function toPairs(points: number[]): [number, number][] {
  const pairs: [number, number][] = []
  for (let i = 0; i + 1 < points.length; i += 2) {
    pairs.push([points[i], points[i + 1]])
  }
  return pairs
}

const round = (n: number) => Math.round(n * 10) / 10

/**
 * Ramer-Douglas-Peucker: keeps the ends, and the points that stray more than `tolerance` from the line between them.
 */
function simplify(
  pairs: [number, number][],
  tolerance: number
): [number, number][] {
  const keep = new Array<boolean>(pairs.length).fill(false)
  keep[0] = keep[pairs.length - 1] = true
  const stack: [number, number][] = [[0, pairs.length - 1]]
  while (stack.length) {
    const [first, last] = stack.pop()!
    let furthest = -1
    let distance = tolerance
    for (let i = first + 1; i < last; i++) {
      const d = distanceToSegment(pairs[i], pairs[first], pairs[last])
      if (d > distance) {
        furthest = i
        distance = d
      }
    }
    if (furthest !== -1) {
      keep[furthest] = true
      stack.push([first, furthest], [furthest, last])
    }
  }
  return pairs.filter((_, i) => keep[i])
}

function distanceToSegment(
  [px, py]: [number, number],
  [ax, ay]: [number, number],
  [bx, by]: [number, number]
): number {
  const dx = bx - ax
  const dy = by - ay
  const length = dx * dx + dy * dy
  const t =
    length === 0
      ? 0
      : Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / length))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}
