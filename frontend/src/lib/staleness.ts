/**
 * Whether a generated layer's picture is up to date -- and if not, what's changed since it was drawn.
 *
 * The API works it out (by the same rule generation uses to pick what to draw) and sends it with every shot, as
 * `out_of_date`: each layer that needs drawing, with the names of what changed (none, for a layer never drawn).
 * This turns that into what the editor shows.
 */
import type { Layer } from "@/lib/layers"
import type { Shot } from "@/lib/shots"

/** Where a generated layer's picture stands */
export type Freshness =
  | { state: "current" }
  | { state: "undrawn" }
  | { state: "stale"; changes: string[] }

/** What each of a layer's params is called in "Out of date: ... changed" */
const CHANGE_LABELS: Record<string, string> = {
  location_id: "the location",
  facing: "the facing",
  shot_size: "the shot size",
  angle: "the camera angle",
  details: "the details",
  time_of_day: "the time of day",
  atmosphere: "the atmosphere",
  location_description: "the location's description",
  setting: "indoors or outdoors",
  view: "what's on this side",
  north_view: "the north view",
  sketches: "a sketch",
  orientation: "which way it faces",
  action: "the action",
  description: "the description",
}

/**
 * Where a layer's picture stands -- null for a layer that isn't generated (text, images, drawings, groups).
 *
 * A layer with no image is undrawn even if the shot it came with doesn't list it (it was added since the last save).
 *
 * @param layer - The layer, as it is in the editor.
 * @param outOfDate - The shot's `out_of_date`, as last saved.
 */
export function freshness(
  layer: Layer,
  outOfDate: Record<string, string[]>
): Freshness | null {
  if (
    layer.type !== "background" &&
    layer.type !== "character" &&
    layer.type !== "prop"
  ) {
    return null
  }
  const changes = outOfDate[layer.id]
  if (layer.image === null || changes?.length === 0) {
    return { state: "undrawn" }
  }
  return changes ? { state: "stale", changes } : { state: "current" }
}

/**
 * What changed, in words: "the action and the description".
 */
export function changesText(changes: string[]): string {
  return new Intl.ListFormat("en-GB", { type: "conjunction" }).format(
    changes.map((name) => CHANGE_LABELS[name] ?? name.replaceAll("_", " "))
  )
}

/**
 * How many of a shot's layers are out of date (drawn, but something's changed since), and how many aren't drawn yet.
 */
export function shotFreshness(shot: Shot): { stale: number; undrawn: number } {
  const all = Object.values(shot.out_of_date)
  const undrawn = all.filter((changes) => changes.length === 0).length
  return { stale: all.length - undrawn, undrawn }
}
