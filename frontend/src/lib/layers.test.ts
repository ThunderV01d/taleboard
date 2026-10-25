/**
 * Unit tests for the layer graph (lib/layers.ts): walking and editing the tree, the transform maths, and grouping.
 *
 * Run with: npm test
 */
import { Transform as KonvaTransform } from "konva/lib/Util"
import { describe, expect, it } from "vitest"

import {
  addOnTop,
  ancestorsOf,
  descendantsOf,
  dropLayer,
  hasBackground,
  invert,
  moveLayerTo,
  newBackgroundLayer,
  newGroupLayer,
  decompose,
  findLayer,
  fromKonva,
  groupLayers,
  moveLayer,
  multiply,
  newImageLayer,
  newTextLayer,
  placedAt,
  removeLayers,
  toKonva,
  toMatrix,
  topLevelOf,
  ungroup,
  updateLayer,
  type GroupLayer,
  type Layer,
  type Matrix,
  type Transform,
} from "@/lib/layers"

/** An image layer with a fixed ID and transform */
function image(id: string, transform: Partial<Transform> = {}): Layer {
  return {
    ...newImageLayer(null, id),
    id,
    transform: { ...placedAt(0, 0), ...transform },
  }
}

/** A group with a fixed ID, transform and children */
function group(
  id: string,
  children: Layer[],
  transform: Partial<Transform> = {}
): GroupLayer {
  return {
    id,
    name: id,
    type: "group",
    opacity: 1,
    visible: true,
    transform: { ...placedAt(0, 0), ...transform },
    children,
  }
}

const ids = (layers: Layer[]) => layers.map((layer) => layer.id)

/** Where a point ends up under a matrix */
function apply(
  [a, b, c, d, e, f]: Matrix,
  [x, y]: [number, number]
): [number, number] {
  return [a * x + c * y + e, b * x + d * y + f]
}

function expectSameMatrix(actual: Matrix, expected: Matrix) {
  actual.forEach((value, i) => expect(value).toBeCloseTo(expected[i], 6))
}

describe("walking and editing the tree", () => {
  const tree = [
    image("a"),
    group("g", [image("b"), group("h", [image("c")])]),
    image("d"),
  ]

  it("finds a layer at any depth, with its parent and position", () => {
    const found = findLayer(tree, "c")!
    expect(found.layer.id).toBe("c")
    expect(found.parent?.id).toBe("h")
    expect(found.index).toBe(0)
    expect(findLayer(tree, "missing")).toBeNull()
  })

  it("names the top-level layer a nested one belongs to", () => {
    expect(topLevelOf(tree, "c")).toBe("g")
    expect(topLevelOf(tree, "a")).toBe("a")
    expect(topLevelOf(tree, "missing")).toBeNull()
  })

  it("updates a nested layer without touching anything else", () => {
    const next = updateLayer(tree, "c", (layer) => ({
      ...layer,
      name: "renamed",
    }))
    expect(findLayer(next, "c")!.layer.name).toBe("renamed")
    expect(next[0]).toBe(tree[0]) // Untouched layers are the same objects -- undo history stays cheap
    expect(findLayer(tree, "c")!.layer.name).toBe("c") // The original is unchanged
  })

  it("removes layers anywhere, and a group with everything in it", () => {
    expect(ids(removeLayers(tree, ["a", "d"]))).toEqual(["g"])
    expect(findLayer(removeLayers(tree, ["c"]), "c")).toBeNull()
    expect(ids(removeLayers(tree, ["g"]))).toEqual(["a", "d"])
  })

  it("moves a layer among its own siblings only, and not past either end", () => {
    expect(ids(moveLayer(tree, "a", 1))).toEqual(["g", "a", "d"])
    expect(ids(moveLayer(tree, "a", -1))).toEqual(["a", "g", "d"])
    expect(ids(moveLayer(tree, "d", 1))).toEqual(["a", "g", "d"])
    const inGroup = moveLayer(tree, "b", 1)
    expect(ids((inGroup[1] as GroupLayer).children)).toEqual(["h", "b"])
  })

  it("adds a new layer on top", () => {
    const text = newTextLayer()
    expect(addOnTop(tree, text).at(-1)).toBe(text)
  })
})

describe("transform maths", () => {
  const transforms: Transform[] = [
    placedAt(512, 512),
    {
      x: 100,
      y: 200,
      scale_x: 2,
      scale_y: 0.5,
      rotation: 30,
      skew_x: 0,
      skew_y: 0,
    },
    {
      x: -40,
      y: 10,
      scale_x: -1,
      scale_y: 1,
      rotation: 0,
      skew_x: 15,
      skew_y: 0,
    },
    {
      x: 7,
      y: 9,
      scale_x: 1.5,
      scale_y: -2,
      rotation: -120,
      skew_x: -20,
      skew_y: 10,
    },
  ]

  it("leaves the identity's content where it is, apart from the move", () => {
    expect(apply(toMatrix(placedAt(10, 20)), [5, 5])).toEqual([15, 25])
  })

  it("rotates clockwise on screen (y points down)", () => {
    const [x, y] = apply(toMatrix({ ...placedAt(0, 0), rotation: 90 }), [1, 0])
    expect(x).toBeCloseTo(0)
    expect(y).toBeCloseTo(1)
  })

  it.each(transforms)(
    "decomposes back to a transform that draws the same: %o",
    (t) => {
      expectSameMatrix(toMatrix(decompose(toMatrix(t))), toMatrix(t))
    }
  )

  it.each(transforms)("round-trips through Konva's attributes: %o", (t) => {
    const back = fromKonva(toKonva(t))
    for (const key of Object.keys(t) as (keyof Transform)[]) {
      expect(back[key]).toBeCloseTo(t[key], 9)
    }
  })

  it.each(transforms)(
    "matches the matrix Konva itself builds for a node: %o",
    (t) => {
      const k = toKonva(t)
      const konva = new KonvaTransform() // The same steps, in the same order, as Konva's Node.getTransform
      konva.translate(k.x, k.y)
      konva.rotate((k.rotation * Math.PI) / 180)
      konva.skew(k.skewX, k.skewY)
      konva.scale(k.scaleX, k.scaleY)
      expectSameMatrix(konva.getMatrix() as Matrix, toMatrix(t))
    }
  )

  it("multiplies in the right order (the right-hand matrix applies first)", () => {
    const scale = toMatrix({ ...placedAt(0, 0), scale_x: 2, scale_y: 2 })
    const move = toMatrix(placedAt(10, 0))
    expect(apply(multiply(move, scale), [1, 1])).toEqual([12, 2])
    expect(apply(multiply(scale, move), [1, 1])).toEqual([22, 2])
  })
})

describe("grouping", () => {
  it("groups siblings around the middle of their centres, without moving them", () => {
    const layers = [
      image("a", { x: 100, y: 100 }),
      image("b", { x: 300, y: 500 }),
      image("c"),
    ]

    const result = groupLayers(layers, ["b", "a"])!

    expect(ids(result.layers)).toEqual([result.groupId, "c"])
    const made = result.layers[0] as GroupLayer
    expect([made.transform.x, made.transform.y]).toEqual([200, 300])
    expect(ids(made.children)).toEqual(["a", "b"]) // Drawing order kept, whatever order they were picked in
    expect(made.children.map((c) => [c.transform.x, c.transform.y])).toEqual([
      [-100, -200],
      [100, 200],
    ])
  })

  it("puts the group where the topmost of its layers was", () => {
    const layers = [image("a"), image("b"), image("c"), image("d")]

    const result = groupLayers(layers, ["a", "c"])!

    expect(ids(result.layers)).toEqual(["b", result.groupId, "d"])
  })

  it("groups inside a group", () => {
    const layers = [group("g", [image("a"), image("b"), image("c")])]

    const result = groupLayers(layers, ["a", "b"])!

    expect(ids((result.layers[0] as GroupLayer).children)).toEqual([
      result.groupId,
      "c",
    ])
  })

  it("refuses layers that aren't siblings", () => {
    const layers = [image("a"), group("g", [image("b")])]
    expect(groupLayers(layers, ["a", "b"])).toBeNull()
    expect(groupLayers(layers, ["a", "missing"])).toBeNull()
  })

  it("ungroups without moving anything on the canvas, however the group was transformed", () => {
    const child = image("a", {
      x: 30,
      y: -10,
      scale_x: 1.5,
      rotation: 20,
      skew_x: 10,
    })
    const g = group("g", [child], {
      x: 400,
      y: 300,
      scale_x: -2,
      scale_y: 0.75,
      rotation: 45,
      skew_x: -15,
      skew_y: 5,
    })

    const [freed] = ungroup([g], "g")

    // Every point of the child's content lands in the same place before and after
    const before = multiply(toMatrix(g.transform), toMatrix(child.transform))
    expectSameMatrix(toMatrix(freed.transform), before)
  })

  it("folds the group's opacity and visibility into its children", () => {
    const g = {
      ...group("g", [{ ...image("a"), opacity: 0.5 }, image("b")]),
      opacity: 0.5,
      visible: false,
    }

    const freed = ungroup([image("x"), g, image("y")], "g")

    expect(ids(freed)).toEqual(["x", "a", "b", "y"])
    expect(freed[1].opacity).toBeCloseTo(0.25)
    expect(freed.slice(1, 3).every((layer) => !layer.visible)).toBe(true)
  })

  it("leaves the tree alone when asked to ungroup something that isn't a group", () => {
    const layers = [image("a")]
    expect(ungroup(layers, "a")).toBe(layers)
  })
})

/** Where a layer's content ends up in frame space: its own transform inside every enclosing group's */
function inFrame(layers: Layer[], id: string): Matrix {
  const own = findLayer(layers, id)!.layer.transform
  return [
    ...ancestorsOf(layers, id).map((g) => g.transform),
    own,
  ].reduce<Matrix>((m, t) => multiply(m, toMatrix(t)), [1, 0, 0, 1, 0, 0])
}

describe("moving layers between groups", () => {
  const tilted = {
    x: 400,
    y: 300,
    scale_x: 1.5,
    scale_y: -0.8,
    rotation: 30,
    skew_x: 12,
    skew_y: -5,
  }
  const tree = () => [
    image("a", { x: 100, y: 120, rotation: 10 }),
    group(
      "g",
      [
        image("b", { x: 20, y: -30, scale_x: 2 }),
        group("h", [image("c", { x: 5, y: 5 })], { rotation: -40, x: 10 }),
      ],
      tilted
    ),
    image("d", { x: 700, y: 700 }),
  ]

  it("inverts a matrix", () => {
    const m = toMatrix({
      ...placedAt(30, 40),
      scale_x: 2,
      rotation: 25,
      skew_x: 10,
    })
    expectSameMatrix(multiply(m, invert(m)), [1, 0, 0, 1, 0, 0])
  })

  it("lists a layer's groups, outermost first", () => {
    expect(ancestorsOf(tree(), "c").map((g) => g.id)).toEqual(["g", "h"])
    expect(ancestorsOf(tree(), "a")).toEqual([])
  })

  it.each([
    ["out of two transformed groups to the top", "c", null],
    ["into a transformed group from the top", "a", "g"],
    ["into a group inside a group", "d", "h"],
    ["from one group to another", "b", "h"],
  ])(
    "keeps a layer's place on the canvas when moving it %s",
    (_, id, parentId) => {
      const before = inFrame(tree(), id)
      const moved = moveLayerTo(tree(), id, parentId, 0)
      expect(findLayer(moved, id)!.parent?.id ?? null).toBe(parentId)
      expectSameMatrix(inFrame(moved, id), before)
    }
  )

  it("never moves a group into itself or one of its own groups", () => {
    const layers = tree()
    expect(moveLayerTo(layers, "g", "h", 0)).toBe(layers)
    expect(moveLayerTo(layers, "g", "g", 0)).toBe(layers)
  })

  it("drops above a layer to put it in front, and below to put it behind (the panel lists the top first)", () => {
    const flat = [image("a"), image("b"), image("c")]
    expect(ids(dropLayer(flat, "a", "c", "above")!.layers)).toEqual([
      "b",
      "c",
      "a",
    ])
    expect(ids(dropLayer(flat, "a", "c", "below")!.layers)).toEqual([
      "b",
      "a",
      "c",
    ])
    expect(ids(dropLayer(flat, "c", "a", "below")!.layers)).toEqual([
      "c",
      "a",
      "b",
    ])
  })

  it("drops next to a layer inside a group into that group", () => {
    const result = dropLayer(tree(), "d", "b", "above")!
    expect(ids((result.layers[1] as GroupLayer).children)).toEqual([
      "b",
      "d",
      "h",
    ])
    expect(result.select).toBe("d")
  })

  it("drops onto a group to put the layer on top of its contents", () => {
    const result = dropLayer(tree(), "a", "g", "onto")!
    expect(ids((result.layers[0] as GroupLayer).children)).toEqual([
      "b",
      "h",
      "a",
    ])
  })

  it("drops onto any other layer to group the two, where that layer was, with the dropped one in front", () => {
    const result = dropLayer(
      [image("a"), image("b"), image("c")],
      "c",
      "a",
      "onto"
    )!
    expect(ids(result.layers)).toEqual([result.select, "b"])
    expect(ids((result.layers[0] as GroupLayer).children)).toEqual(["a", "c"])
  })

  it("keeps everything in place when grouping by a drop", () => {
    const before = inFrame(tree(), "c")
    const result = dropLayer(tree(), "c", "d", "onto")!
    expectSameMatrix(inFrame(result.layers, "c"), before)
  })

  it("refuses drops onto itself, or of a group into its own contents", () => {
    expect(dropLayer(tree(), "a", "a", "onto")).toBeNull()
    expect(dropLayer(tree(), "g", "c", "above")).toBeNull()
    expect(dropLayer(tree(), "g", "h", "onto")).toBeNull()
  })
})

describe("backgrounds, groups and what a delete takes with it", () => {
  it("finds a background at any depth", () => {
    expect(hasBackground([image("a")])).toBe(false)
    expect(hasBackground([newBackgroundLayer()])).toBe(true)
    expect(hasBackground([group("g", [newBackgroundLayer()])])).toBe(true)
  })

  it("makes an empty group and a fresh, undrawn background", () => {
    expect(newGroupLayer().children).toEqual([])
    const background = newBackgroundLayer()
    expect(
      background.type === "background" && [background.facing, background.image]
    ).toEqual(["north", null])
  })

  it("lists everything inside a group, top first, nested groups included", () => {
    const g = group("g", [image("a"), group("h", [image("b"), image("c")])])
    expect(ids(descendantsOf(g))).toEqual(["h", "c", "b", "a"])
  })
})
