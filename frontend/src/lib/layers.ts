/**
 * A shot's layer graph: building layers, walking and editing the tree, and the transform maths.
 *
 * Everything here is pure -- it takes a layer list and returns a new one -- so the canvas editor can keep every
 * version for undo, and the functions can be unit-tested (layers.test.ts).
 *
 * Coordinates: a layer's transform places its *centre*, in its parent's space. At the top level that's the
 * 1024-pixel frame; inside a group it's relative to the group's own centre, which is the group's pivot. Rotation and
 * skew are in degrees, as the backend stores them.
 */
import type { components } from "@/api/schema"
import type { Character, Prop } from "@/lib/registries"

type Schemas = components["schemas"]
export type Transform = Schemas["Transform-Output"]
export type Layer = Schemas["ShotOut"]["layers"][number]
export type LayerType = Layer["type"]
export type GroupLayer = Extract<Layer, { type: "group" }>
export type TextLayer = Extract<Layer, { type: "text" }>

/** Shots are drawn on a square frame of this many pixels a side (matches the backend's FRAME_SIZE) */
export const FRAME_SIZE = 1024

/** A new layer's ID, in the same form the backend makes them (32 hex characters) */
export function newId(): string {
  return crypto.randomUUID().replaceAll("-", "")
}

/**
 * A transform that leaves a layer unrotated and unskewed -- centred on (x, y), at the given scale (default 1).
 */
export function placedAt(x: number, y: number, scale = 1): Transform {
  return { x, y, scale_x: scale, scale_y: scale, rotation: 0, skew_x: 0, skew_y: 0 }
}

const CENTRE = FRAME_SIZE / 2

/**
 * New character and prop layers' scales. Their images are fitted to a standard size (characters 1024 pixels tall,
 * props 512 on their longer side), so these are the same as a story import's medium-sized figure in the middle row:
 * a character 45% of the frame tall (times 0.85 for the row), a prop 15%.
 */
const CHARACTER_SCALE = 0.45 * 0.85
const PROP_SCALE = (0.15 * 0.85 * FRAME_SIZE) / 512

/** Where the middle row's feet stand */
const FLOOR_Y = FRAME_SIZE * 0.86

function base(name: string, x = CENTRE, y = CENTRE, scale = 1) {
  return {
    id: newId(),
    name,
    transform: placedAt(x, y, scale),
    opacity: 1,
    visible: true,
  }
}

/**
 * A background, not drawn yet -- it fills the frame, and is drawn from the scene's location facing north.
 */
export function newBackgroundLayer(): Layer {
  return {
    ...base("Background"),
    type: "background",
    facing: "north",
    image: null,
    corners: null,
    last_generated_params: null,
  }
}

/**
 * An empty group, centred on the frame (layers dragged into it keep their place on the canvas).
 */
export function newGroupLayer(): GroupLayer {
  return { ...base("Group"), type: "group", children: [] }
}

export function newTextLayer(): TextLayer {
  return {
    ...base("Text", CENTRE, FRAME_SIZE * 0.85),
    type: "text",
    text: "Caption",
    font: "sans",
    size: 48,
    colour: "#000000",
    align: "center",
  }
}

export function newImageLayer(image: string | null, name = "Image"): Layer {
  return { ...base(name), type: "image", image, corners: null }
}

export function newCharacterLayer(
  character: Character,
  x = CENTRE,
  y = FLOOR_Y - (CHARACTER_SCALE * FRAME_SIZE) / 2
): Layer {
  return {
    ...base(character.name, x, y, CHARACTER_SCALE),
    type: "character",
    character_id: character.id,
    orientation: "towards_camera",
    action: "",
    image: null,
    corners: null,
    last_generated_params: null,
  }
}

export function newPropLayer(prop: Prop): Layer {
  return {
    ...base(prop.name, CENTRE, FLOOR_Y - (PROP_SCALE * 512) / 2, PROP_SCALE),
    type: "prop",
    prop_id: prop.id,
    orientation: "towards_camera",
    image: null,
    corners: null,
    last_generated_params: null,
  }
}

/**
 * Character layers for a new shot, spread evenly across the frame, standing on the middle row's floor. Not generated
 * yet -- they have no image until the character's pose is drawn.
 */
export function characterLayers(characters: Character[]): Layer[] {
  return characters.map((character, i) =>
    newCharacterLayer(
      character,
      (FRAME_SIZE * (i + 1)) / (characters.length + 1)
    )
  )
}

// --- Walking the tree -------------------------------------------------------------------------------------------

/** Where a layer sits: its siblings (the list it's in), its index there, and its group (null at the top level) */
export type Place = {
  layer: Layer
  siblings: Layer[]
  index: number
  parent: GroupLayer | null
}

/**
 * Finds a layer anywhere in the tree.
 */
export function findLayer(
  layers: Layer[],
  id: string,
  parent: GroupLayer | null = null
): Place | null {
  for (const [index, layer] of layers.entries()) {
    if (layer.id === id) {
      return { layer, siblings: layers, index, parent }
    }
    if (layer.type === "group") {
      const found = findLayer(layer.children, id, layer)
      if (found) {
        return found
      }
    }
  }
  return null
}

/**
 * The top-level layer a layer belongs to (itself, if it isn't in a group) -- what a click on the canvas selects.
 */
export function topLevelOf(layers: Layer[], id: string): string | null {
  for (const layer of layers) {
    if (
      layer.id === id ||
      (layer.type === "group" && findLayer(layer.children, id))
    ) {
      return layer.id
    }
  }
  return null
}

/**
 * Rewrites the list (or the group's children) that holds the given layer, leaving the rest of the tree as it was.
 */
function withSiblings(
  layers: Layer[],
  id: string,
  change: (siblings: Layer[]) => Layer[]
): Layer[] {
  if (layers.some((layer) => layer.id === id)) {
    return change(layers)
  }
  return layers.map((layer) =>
    layer.type === "group" && findLayer(layer.children, id)
      ? { ...layer, children: withSiblings(layer.children, id, change) }
      : layer
  )
}

/**
 * Replaces one layer, wherever it is, with `change(layer)`.
 */
export function updateLayer(
  layers: Layer[],
  id: string,
  change: (layer: Layer) => Layer
): Layer[] {
  return withSiblings(layers, id, (siblings) =>
    siblings.map((layer) => (layer.id === id ? change(layer) : layer))
  )
}

/**
 * Removes layers (and, with a group, everything in it).
 */
export function removeLayers(layers: Layer[], ids: string[]): Layer[] {
  return layers
    .filter((layer) => !ids.includes(layer.id))
    .map((layer) =>
      layer.type === "group"
        ? { ...layer, children: removeLayers(layer.children, ids) }
        : layer
    )
}

/**
 * Moves a layer one step up (+1, drawn later, so in front) or down (-1) among its siblings.
 */
export function moveLayer(layers: Layer[], id: string, step: 1 | -1): Layer[] {
  return withSiblings(layers, id, (siblings) => {
    const from = siblings.findIndex((layer) => layer.id === id)
    const to = from + step
    if (to < 0 || to >= siblings.length) {
      return siblings
    }
    const next = [...siblings]
    ;[next[from], next[to]] = [next[to], next[from]]
    return next
  })
}

/**
 * Adds a layer on top of everything.
 */
export function addOnTop(layers: Layer[], layer: Layer): Layer[] {
  return [...layers, layer]
}

// --- Transform maths --------------------------------------------------------------------------------------------

/** A 2D affine matrix [a, b, c, d, e, f]: x' = a*x + c*y + e, y' = b*x + d*y + f (the same layout as Konva's) */
export type Matrix = [number, number, number, number, number, number]

const radians = (degrees: number) => (degrees * Math.PI) / 180
const degrees = (radians: number) => (radians * 180) / Math.PI

/**
 * The matrix a transform applies to a layer's centred content: translate, rotate, skew, then scale -- in the same
 * order Konva draws a node, so the canvas and these sums always agree.
 */
export function toMatrix(t: Transform): Matrix {
  const cos = Math.cos(radians(t.rotation))
  const sin = Math.sin(radians(t.rotation))
  const kx = Math.tan(radians(t.skew_x))
  const ky = Math.tan(radians(t.skew_y))
  // R . K, where K = [[1, kx], [ky, 1]]
  const a = cos - sin * ky
  const b = sin + cos * ky
  const c = cos * kx - sin
  const d = sin * kx + cos
  // . S
  return [a * t.scale_x, b * t.scale_x, c * t.scale_y, d * t.scale_y, t.x, t.y]
}

/**
 * m1 . m2 -- applying m2 first, then m1.
 */
export function multiply(m1: Matrix, m2: Matrix): Matrix {
  const [a1, b1, c1, d1, e1, f1] = m1
  const [a2, b2, c2, d2, e2, f2] = m2
  return [
    a1 * a2 + c1 * b2,
    b1 * a2 + d1 * b2,
    a1 * c2 + c1 * d2,
    b1 * c2 + d1 * d2,
    a1 * e2 + c1 * f2 + e1,
    b1 * e2 + d1 * f2 + f1,
  ]
}

/**
 * The transform for a matrix (any affine matrix can be written as translate . rotate . skew-x . scale). The same
 * decomposition Konva uses, so a decomposed transform draws exactly as the matrix would.
 */
export function decompose([a, b, c, d, e, f]: Matrix): Transform {
  const delta = a * d - b * c
  const r = Math.hypot(a, b)
  if (r === 0) {
    return {
      x: e,
      y: f,
      scale_x: 0,
      scale_y: 0,
      rotation: 0,
      skew_x: 0,
      skew_y: 0,
    }
  }
  return {
    x: e,
    y: f,
    rotation: degrees(b > 0 ? Math.acos(a / r) : -Math.acos(a / r)),
    scale_x: r,
    scale_y: delta / r,
    skew_x: delta === 0 ? 0 : degrees(Math.atan((a * c + b * d) / delta)),
    skew_y: 0,
  }
}

// --- Groups -----------------------------------------------------------------------------------------------------

/**
 * Puts layers that share a parent into a new group, keeping where they appear: the group's pivot is the middle of
 * their centres, and each moves into the group's space relative to it. The group takes the topmost layer's place.
 *
 * Returns the new layers and the group's ID, or null when the layers aren't all siblings.
 */
export function groupLayers(
  layers: Layer[],
  ids: string[]
): { layers: Layer[]; groupId: string } | null {
  const places = ids.map((id) => findLayer(layers, id))
  if (
    places.length === 0 ||
    places.some((p) => !p || p.siblings !== places[0]!.siblings)
  ) {
    return null
  }
  const siblings = places[0]!.siblings
  const chosen = siblings.filter((layer) => ids.includes(layer.id)) // In drawing order
  const cx = chosen.reduce((sum, l) => sum + l.transform.x, 0) / chosen.length
  const cy = chosen.reduce((sum, l) => sum + l.transform.y, 0) / chosen.length
  const group: GroupLayer = {
    ...base("Group", cx, cy),
    type: "group",
    children: chosen.map((layer) => ({
      ...layer,
      transform: {
        ...layer.transform,
        x: layer.transform.x - cx,
        y: layer.transform.y - cy,
      },
    })),
  }
  const topmost = Math.max(...chosen.map((layer) => siblings.indexOf(layer)))
  const regrouped = withSiblings(layers, ids[0], (list) =>
    list.flatMap((layer, i) =>
      i === topmost ? [group] : ids.includes(layer.id) ? [] : [layer]
    )
  )
  return { layers: regrouped, groupId: group.id }
}

/**
 * Dissolves a group, putting its children back in its place -- each with the group's transform, opacity and
 * visibility folded into its own, so nothing on the canvas moves.
 */
export function ungroup(layers: Layer[], groupId: string): Layer[] {
  const place = findLayer(layers, groupId)
  if (!place || place.layer.type !== "group") {
    return layers
  }
  const group = place.layer
  const groupMatrix = toMatrix(group.transform)
  const children = group.children.map((child) => ({
    ...child,
    transform: decompose(multiply(groupMatrix, toMatrix(child.transform))),
    opacity: child.opacity * group.opacity,
    visible: child.visible && group.visible,
  }))
  return withSiblings(layers, groupId, (siblings) =>
    siblings.flatMap((layer) => (layer.id === groupId ? children : [layer]))
  )
}

// --- Moving layers around the tree ------------------------------------------------------------------------------

/**
 * The inverse of an affine matrix -- undoes it. A matrix that squashes everything flat (a scale of 0) has no inverse,
 * so the identity stands in.
 */
export function invert([a, b, c, d, e, f]: Matrix): Matrix {
  const det = a * d - b * c
  if (det === 0) {
    return [1, 0, 0, 1, 0, 0]
  }
  return [
    d / det,
    -b / det,
    -c / det,
    a / det,
    (c * f - d * e) / det,
    (b * e - a * f) / det,
  ]
}

/**
 * The groups a layer sits inside, outermost first (empty at the top level).
 */
export function ancestorsOf(layers: Layer[], id: string): GroupLayer[] {
  for (const layer of layers) {
    if (layer.id === id) {
      return []
    }
    if (layer.type === "group") {
      if (layer.children.some((child) => child.id === id)) {
        return [layer]
      }
      const deeper = ancestorsOf(layer.children, id)
      if (deeper.length > 0 || findLayer(layer.children, id)) {
        return [layer, ...deeper]
      }
    }
  }
  return []
}

/**
 * What a layer's parent space is, in frame space: every enclosing group's transform, outermost first. For a layer at
 * the top level, the identity.
 */
function parentMatrix(layers: Layer[], id: string): Matrix {
  return ancestorsOf(layers, id).reduce<Matrix>(
    (m, group) => multiply(m, toMatrix(group.transform)),
    [1, 0, 0, 1, 0, 0]
  )
}

/**
 * What a layer's own space is, in frame space: its parents' transforms, then its own.
 */
export function frameMatrixOf(layers: Layer[], layer: Layer): Matrix {
  return multiply(parentMatrix(layers, layer.id), toMatrix(layer.transform))
}

/**
 * A point moved by a matrix.
 */
export function apply(
  [a, b, c, d, e, f]: Matrix,
  { x, y }: { x: number; y: number }
): { x: number; y: number } {
  return { x: a * x + c * y + e, y: b * x + d * y + f }
}

/** Where a layer can be dropped in the layers panel, relative to the row it's dropped on */
export type DropZone = "above" | "below" | "onto"

/**
 * Takes a layer out of wherever it is and puts it into another parent (a group's ID, or null for the top level) at an
 * index of that parent's list -- without moving it on the canvas: its transform is converted into the new parent's
 * space. Moving a group into itself, or into one of its own groups, changes nothing.
 */
export function moveLayerTo(
  layers: Layer[],
  id: string,
  parentId: string | null,
  index: number
): Layer[] {
  const place = findLayer(layers, id)
  if (!place || parentId === id) {
    return layers
  }
  if (
    parentId !== null &&
    place.layer.type === "group" &&
    findLayer(place.layer.children, parentId)
  ) {
    return layers
  }
  const inFrame = multiply(
    parentMatrix(layers, id),
    toMatrix(place.layer.transform)
  )
  const removed = removeLayers(layers, [id])
  const newParent =
    parentId === null ? null : findLayer(removed, parentId)?.layer
  if (parentId !== null && newParent?.type !== "group") {
    return layers
  }
  const into =
    parentId === null
      ? ([1, 0, 0, 1, 0, 0] as Matrix)
      : multiply(
          parentMatrix(removed, parentId),
          toMatrix(newParent!.transform)
        )
  const moved: Layer = {
    ...place.layer,
    transform: decompose(multiply(invert(into), inFrame)),
  }
  const insert = (list: Layer[]) => {
    const at = Math.max(0, Math.min(index, list.length))
    return [...list.slice(0, at), moved, ...list.slice(at)]
  }
  if (parentId === null) {
    return insert(removed)
  }
  return updateLayer(removed, parentId, (group) =>
    group.type === "group"
      ? { ...group, children: insert(group.children) }
      : group
  )
}

/**
 * Drops one layer on another's row in the layers panel (which lists the top of the stack first):
 * - "above" or "below" the row: next to that layer, in front of or behind it, in the same group;
 * - "onto" a group: into it, on top of its other layers;
 * - "onto" any other layer: the two become a new group, where that layer was.
 *
 * Returns the new layers and what to select afterwards, or null when the drop makes no sense (onto itself, or a
 * group into its own contents).
 */
export function dropLayer(
  layers: Layer[],
  draggedId: string,
  targetId: string,
  zone: DropZone
): { layers: Layer[]; select: string } | null {
  const dragged = findLayer(layers, draggedId)
  const target = findLayer(layers, targetId)
  if (!dragged || !target || draggedId === targetId) {
    return null
  }
  if (
    dragged.layer.type === "group" &&
    findLayer(dragged.layer.children, targetId)
  ) {
    return null
  }
  if (zone === "onto" && target.layer.type === "group") {
    const next = moveLayerTo(
      layers,
      draggedId,
      targetId,
      Number.MAX_SAFE_INTEGER
    )
    return next === layers ? null : { layers: next, select: draggedId }
  }
  // Next to the target (just in front of it when grouping), in the target's parent
  const parentId = target.parent?.id ?? null
  const withoutDragged = removeLayers(layers, [draggedId])
  const targetIndex = findLayer(withoutDragged, targetId)!.index
  const next = moveLayerTo(
    layers,
    draggedId,
    parentId,
    zone === "below" ? targetIndex : targetIndex + 1
  )
  if (next === layers) {
    return null
  }
  if (zone !== "onto") {
    return { layers: next, select: draggedId }
  }
  const grouped = groupLayers(next, [targetId, draggedId])
  return grouped && { layers: grouped.layers, select: grouped.groupId }
}

/**
 * True if the shot already has a background (at any depth) -- a shot has one at most.
 */
export function hasBackground(layers: Layer[]): boolean {
  return layers.some(
    (layer) =>
      layer.type === "background" ||
      (layer.type === "group" && hasBackground(layer.children))
  )
}

/**
 * Every layer inside a group, at any depth, listed top first -- what deleting the group takes with it.
 */
export function descendantsOf(group: GroupLayer): Layer[] {
  return [...group.children]
    .reverse()
    .flatMap((child) =>
      child.type === "group" ? [child, ...descendantsOf(child)] : [child]
    )
}

// --- Konva ------------------------------------------------------------------------------------------------------

/**
 * A transform as Konva node attributes. Konva's skew is a shear factor, not an angle, hence the tangent.
 */
export function toKonva(t: Transform) {
  return {
    x: t.x,
    y: t.y,
    scaleX: t.scale_x,
    scaleY: t.scale_y,
    rotation: t.rotation,
    skewX: Math.tan(radians(t.skew_x)),
    skewY: Math.tan(radians(t.skew_y)),
  }
}

/**
 * Konva node attributes (after a drag or a resize on the canvas) as a transform.
 */
export function fromKonva(node: {
  x: number
  y: number
  scaleX: number
  scaleY: number
  rotation: number
  skewX: number
  skewY: number
}): Transform {
  return {
    x: node.x,
    y: node.y,
    scale_x: node.scaleX,
    scale_y: node.scaleY,
    rotation: node.rotation,
    skew_x: degrees(Math.atan(node.skewX)),
    skew_y: degrees(Math.atan(node.skewY)),
  }
}
