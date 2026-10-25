/**
 * Perspective warp ("Distort"): pulling a picture's four corners to new places, as in an image editor -- eg:- to
 * straighten a wall that was generated at a slight angle.
 *
 * Corners are fractions of the picture's own width and height, before the layer's transform: (0, 0) is its top-left
 * and (1, 1) its bottom-right, so they can go past its edges. The picture is mapped onto them by a projective
 * transform (a homography), so straight lines stay straight, as in a photo of a flat surface taken at an angle.
 *
 * A 2D canvas can't draw that directly, so the picture is cut into a grid of small triangles and each is drawn with
 * the affine transform that fits it. Milestone 4's compositor must use the same mapping (Pillow's
 * Image.transform(..., Image.PERSPECTIVE) is one).
 */
import type { components } from "@/api/schema"
import type { Layer } from "@/lib/layers"

export type Corners = components["schemas"]["Corners-Output"]
export type Point = { x: number; y: number }
export type CornerName = keyof Corners

/** The corners in order, clockwise from the top-left */
export const CORNER_NAMES: CornerName[] = [
  "top_left",
  "top_right",
  "bottom_right",
  "bottom_left",
]

/** Where the corners start: the picture as it is */
export const UNWARPED: Corners = {
  top_left: { x: 0, y: 0 },
  top_right: { x: 1, y: 0 },
  bottom_right: { x: 1, y: 1 },
  bottom_left: { x: 0, y: 1 },
}

/** A layer drawn from a picture -- the kinds that can be warped */
export type PictureLayer = Exclude<Layer, { type: "text" | "group" }>

export function isPicture(layer: Layer): layer is PictureLayer {
  return layer.type !== "text" && layer.type !== "group"
}

/**
 * True when the corners are where they started (so the layer can store none at all).
 */
export function isUnwarped(corners: Corners): boolean {
  return CORNER_NAMES.every(
    (name) =>
      corners[name].x === UNWARPED[name].x &&
      corners[name].y === UNWARPED[name].y
  )
}

/**
 * True when the corners, in order, turn the same way at every corner -- a convex shape, clockwise on screen. Anything
 * else would fold the picture over itself or turn it inside out, so the backend refuses it (the same check).
 *
 * `minAngle` (degrees) also keeps every corner's angle between it and 180 minus it. A shape that is convex but almost
 * a triangle squeezes most of the picture into one corner, so the Distort handles stop short of one.
 */
export function isConvex(corners: Corners, minAngle = 0): boolean {
  const quad = CORNER_NAMES.map((name) => corners[name])
  const least = Math.sin((minAngle * Math.PI) / 180)
  return quad.every((a, i) => {
    const b = quad[(i + 1) % 4]
    const c = quad[(i + 2) % 4]
    // The turn at b: |ab| |bc| sin(the angle it turns through), positive when clockwise on screen
    const turn = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)
    const lengths =
      Math.hypot(b.x - a.x, b.y - a.y) * Math.hypot(c.x - b.x, c.y - b.y)
    return Number.isFinite(turn) && turn > 0 && turn > lengths * least
  })
}

/**
 * The projective mapping from the unit square onto the corners: (0, 0) goes to the top-left corner, (1, 0) to the
 * top-right, and so on, with straight lines staying straight in between.
 */
export function squareToQuad(
  corners: Corners
): (u: number, v: number) => Point {
  const [p0, p1, p2, p3] = CORNER_NAMES.map((name) => corners[name])
  const sx = p0.x - p1.x + p2.x - p3.x
  const sy = p0.y - p1.y + p2.y - p3.y
  let g = 0
  let h = 0
  if (sx !== 0 || sy !== 0) {
    // Not a parallelogram: solve for the perspective terms (Heckbert, "Fundamentals of Texture Mapping", 1989)
    const dx1 = p1.x - p2.x
    const dx2 = p3.x - p2.x
    const dy1 = p1.y - p2.y
    const dy2 = p3.y - p2.y
    const det = dx1 * dy2 - dx2 * dy1
    g = (sx * dy2 - dx2 * sy) / det
    h = (dx1 * sy - sx * dy1) / det
  }
  const a = p1.x - p0.x + g * p1.x
  const b = p3.x - p0.x + h * p3.x
  const d = p1.y - p0.y + g * p1.y
  const e = p3.y - p0.y + h * p3.y
  return (u, v) => {
    const w = g * u + h * v + 1
    return {
      x: (a * u + b * v + p0.x) / w,
      y: (d * u + e * v + p0.y) / w,
    }
  }
}

/**
 * The box around a picture of this size once warped, in the same units as the size (the picture's top-left at 0, 0).
 */
export function warpedBounds(
  corners: Corners,
  width: number,
  height: number
): { x: number; y: number; width: number; height: number } {
  const xs = CORNER_NAMES.map((name) => corners[name].x * width)
  const ys = CORNER_NAMES.map((name) => corners[name].y * height)
  const x = Math.min(...xs)
  const y = Math.min(...ys)
  return { x, y, width: Math.max(...xs) - x, height: Math.max(...ys) - y }
}

/** The canvas matrix [a, b, c, d, e, f] that takes one triangle onto another */
export type Affine = [number, number, number, number, number, number]

/**
 * The affine transform that takes triangle (s0, s1, s2) onto (d0, d1, d2), in the canvas's order for
 * setTransform -- x' = a x + c y + e, y' = b x + d y + f.
 */
export function affineBetween(
  [s0, s1, s2]: [Point, Point, Point],
  [d0, d1, d2]: [Point, Point, Point]
): Affine {
  // Edge vectors from the first point: the transform's linear part takes the source's onto the destination's
  const sa = s1.x - s0.x
  const sb = s1.y - s0.y
  const sc = s2.x - s0.x
  const sd = s2.y - s0.y
  const det = sa * sd - sc * sb
  const ia = sd / det
  const ib = -sb / det
  const ic = -sc / det
  const id = sa / det
  const da = d1.x - d0.x
  const db = d1.y - d0.y
  const dc = d2.x - d0.x
  const dd = d2.y - d0.y
  const a = da * ia + dc * ib
  const b = db * ia + dd * ib
  const c = da * ic + dc * id
  const d = db * ic + dd * id
  return [a, b, c, d, d0.x - a * s0.x - c * s0.y, d0.y - b * s0.x - d * s0.y]
}

/** Grid cells along each side of the mesh -- enough that the straight-edged pieces look curved where they should */
const MESH = 16

/**
 * Draws a picture warped onto its corners. The picture is `width` by `height` where it's drawn (whatever its own pixel
 * size), with its undistorted top-left at the context's (0, 0).
 */
export function drawWarped(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource & { width: number; height: number },
  width: number,
  height: number,
  corners: Corners
) {
  const map = squareToQuad(corners)
  const grid: Point[][] = []
  for (let i = 0; i <= MESH; i++) {
    grid.push([])
    for (let j = 0; j <= MESH; j++) {
      const p = map(i / MESH, j / MESH)
      grid[i].push({ x: p.x * width, y: p.y * height })
    }
  }
  const source = (i: number, j: number): Point => ({
    x: (i / MESH) * image.width,
    y: (j / MESH) * image.height,
  })
  for (let i = 0; i < MESH; i++) {
    for (let j = 0; j < MESH; j++) {
      const cell = { i, j }
      triangle(context, image, cell, [
        [source(i, j), source(i + 1, j), source(i + 1, j + 1)],
        [grid[i][j], grid[i + 1][j], grid[i + 1][j + 1]],
      ])
      triangle(context, image, cell, [
        [source(i, j), source(i + 1, j + 1), source(i, j + 1)],
        [grid[i][j], grid[i + 1][j + 1], grid[i][j + 1]],
      ])
    }
  }
}

/**
 * One piece of the mesh: the source triangle's part of the picture, drawn into the destination triangle. Each is
 * clipped a fraction of a pixel larger than it is, so neighbours overlap and no hairline gaps show between them.
 */
function triangle(
  context: CanvasRenderingContext2D,
  image: CanvasImageSource & { width: number; height: number },
  { i, j }: { i: number; j: number },
  [from, to]: [[Point, Point, Point], [Point, Point, Point]]
) {
  const cx = (to[0].x + to[1].x + to[2].x) / 3
  const cy = (to[0].y + to[1].y + to[2].y) / 3
  const grow = (p: Point) => {
    const dx = p.x - cx
    const dy = p.y - cy
    const length = Math.hypot(dx, dy) || 1
    return { x: p.x + (dx / length) * 0.75, y: p.y + (dy / length) * 0.75 }
  }
  const clip = to.map(grow)
  context.save()
  context.beginPath()
  context.moveTo(clip[0].x, clip[0].y)
  context.lineTo(clip[1].x, clip[1].y)
  context.lineTo(clip[2].x, clip[2].y)
  context.closePath()
  context.clip()
  context.transform(...affineBetween(from, to))
  // Only this cell of the picture (and a pixel around it), not the whole thing, for every one of the triangles
  const cellWidth = image.width / MESH
  const cellHeight = image.height / MESH
  const sx = Math.max(0, i * cellWidth - 1)
  const sy = Math.max(0, j * cellHeight - 1)
  const sw = Math.min(image.width - sx, cellWidth + 2)
  const sh = Math.min(image.height - sy, cellHeight + 2)
  context.drawImage(image, sx, sy, sw, sh, sx, sy, sw, sh)
  context.restore()
}
