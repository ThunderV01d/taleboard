/**
 * The canvas editor's view: how far it's zoomed in, and where it's panned to.
 *
 * Zoom is relative to fitting the frame in the space it's given (1 fits it, 2 shows it twice as large). The pan is how
 * far (in screen pixels) the frame's centre has moved from the middle of that space. The canvas itself never grows --
 * it stays the size of its space, and draws the frame scaled and moved within it -- so zooming in costs nothing extra.
 */

export type View = { zoom: number; x: number; y: number }

/** The frame fitted to its space, centred */
export const FIT: View = { zoom: 1, x: 0, y: 0 }

export const MIN_ZOOM = 0.5
export const MAX_ZOOM = 16

/** How much one step of the zoom buttons (or Ctrl and +/-) zooms by */
export const ZOOM_STEP = 1.25

/**
 * The view zoomed to `zoom` (kept within MIN_ZOOM..MAX_ZOOM) about a point, which stays where it is on screen -- the
 * pointer, for Ctrl and the wheel; the middle of the space, for the buttons.
 *
 * @param view - The view now.
 * @param zoom - The zoom wanted.
 * @param point - The point to zoom about, in screen pixels from the middle of the space. Defaults to the middle.
 */
export function zoomAt(
  view: View,
  zoom: number,
  point: { x: number; y: number } = { x: 0, y: 0 }
): View {
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
  const k = next / view.zoom
  // A point on the frame sits at pan + d * scale from the middle; keeping `point` fixed means pan' = point - (point - pan) * k
  return {
    zoom: next,
    x: point.x - (point.x - view.x) * k,
    y: point.y - (point.y - view.y) * k,
  }
}

/**
 * The view with its pan kept within reach: the frame (drawn `width` by `height` on screen) can be moved off the
 * space only until `keep` pixels of it are left showing.
 */
export function clampPan(
  view: View,
  frame: { width: number; height: number },
  space: { width: number; height: number },
  keep = 48
): View {
  const limit = (frameSize: number, spaceSize: number) =>
    Math.max(0, (frameSize + spaceSize) / 2 - keep)
  const clamp = (value: number, max: number) =>
    Math.max(-max, Math.min(max, value))
  return {
    ...view,
    x: clamp(view.x, limit(frame.width, space.width)),
    y: clamp(view.y, limit(frame.height, space.height)),
  }
}
