import Konva from "konva"
import { useEffect, useMemo, useRef, useState } from "react"
import {
  Circle,
  Group,
  Image as KonvaImage,
  Layer as KonvaLayer,
  Line,
  Rect,
  Stage,
  Text,
  Transformer,
} from "react-konva"
import useImage from "use-image"

import type { Tool } from "@/components/canvas/tool-strip"
import { FONT_FAMILIES } from "@/lib/labels"
import {
  apply,
  findLayer,
  FRAME_SIZE,
  frameMatrixOf,
  fromKonva,
  invert,
  toKonva,
  topLevelOf,
  type Layer,
  type Transform,
} from "@/lib/layers"
import {
  CORNER_NAMES,
  drawWarped,
  isConvex,
  isPicture,
  squareToQuad,
  UNWARPED,
  warpedBounds,
  type CornerName,
  type Corners,
  type PictureLayer,
} from "@/lib/warp"

/**
 * Placeholder sizes (in frame pixels, before the layer's scale) for layers whose image hasn't been drawn or uploaded
 * yet. Drawn characters are fitted to 1024 pixels tall and props to 512 pixels on their longer side, so a layer is
 * about the same size before and after it's drawn.
 */
const PLACEHOLDER_SIZE: Record<
  "character" | "prop" | "image",
  [number, number]
> = {
  character: [360, 1024],
  prop: [512, 512],
  image: [300, 300],
}

/** The largest a warped picture is redrawn at (pixels a side) -- big uploads are drawn smaller rather than at full size */
const MAX_WARP_SIZE = 2048

/** Colour of the corner handles and outline in Distort (Konva's own Transformer blue, so the two modes match) */
const HANDLE_COLOUR = "rgb(0, 161, 255)"

/** The smallest (and 180 minus the largest) angle a Distort handle can make at any corner, in degrees */
const MIN_CORNER_ANGLE = 10

/** Space (in screen pixels) around the frame, so handles on its edges show in full rather than a quarter of them */
const MARGIN = 12

/** Konva name given to the corner handles, so a click on one isn't taken as a click on the layer under it */
const HANDLE_NAME = "warp-handle"

/** Size (in frame pixels) of each square of the transparency checkerboard */
const CHECKER_SQUARE = 24

let checkerTile: HTMLCanvasElement | null = null

/**
 * The grey-and-white checkerboard tile shown wherever the frame is transparent (as in GIMP or Photoshop) -- drawn
 * once, then repeated across the frame by Konva.
 */
function checkerboard(): HTMLCanvasElement {
  if (!checkerTile) {
    checkerTile = document.createElement("canvas")
    checkerTile.width = checkerTile.height = CHECKER_SQUARE * 2
    const g = checkerTile.getContext("2d")!
    g.fillStyle = "#ffffff"
    g.fillRect(0, 0, CHECKER_SQUARE * 2, CHECKER_SQUARE * 2)
    g.fillStyle = "#cccccc"
    g.fillRect(0, 0, CHECKER_SQUARE, CHECKER_SQUARE)
    g.fillRect(CHECKER_SQUARE, CHECKER_SQUARE, CHECKER_SQUARE, CHECKER_SQUARE)
  }
  return checkerTile
}

/** A layer's ID, and its transform after a move or resize on the canvas */
export type TransformChange = { id: string; transform: Transform }

/** A picture's corners while one is being dragged in Distort -- drawn, but not an edit until the drag ends */
type Preview = { id: string; corners: Corners } | null

/**
 * The shot's frame, drawn with Konva: every layer in its place, groups nested, bottom to top.
 *
 * Click a layer to select it (a layer inside a group selects the whole group -- pick it from the layers panel to
 * select just it); shift-click adds to the selection. Selected layers get handles to move, resize and rotate them.
 * Konva does the dragging; the result is reported once, when the drag or resize ends, so each is one undo step.
 *
 * With the Distort tool, selected pictures get a handle on each corner instead, to warp their perspective. A click
 * then picks the picture itself, even inside a group (groups can't be distorted), and nothing moves when dragged.
 */
export function ShotCanvas({
  layers,
  selection,
  tool,
  imageUrl,
  placeholderLabel,
  onSelect,
  onTransform,
  onWarp,
}: {
  layers: Layer[]
  selection: string[]
  tool: Tool
  /** The URL to draw a layer's image from, if it has one */
  imageUrl: (layer: Layer) => string | null
  /** What a not-yet-drawn layer's placeholder says */
  placeholderLabel: (layer: Layer) => string
  onSelect: (ids: string[]) => void
  onTransform: (changes: TransformChange[]) => void
  /** A picture's new corners, once a corner has been dragged */
  onWarp: (id: string, corners: Corners) => void
}) {
  const box = useRef<HTMLDivElement>(null)
  const stage = useRef<Konva.Stage>(null)
  const transformer = useRef<Konva.Transformer>(null)
  const [size, setSize] = useState(600)
  const [preview, setPreview] = useState<Preview>(null)

  // The frame is the largest square that fits the space it's given, whichever way that space is narrower
  useEffect(() => {
    const element = box.current
    if (!element) {
      return
    }
    const observer = new ResizeObserver(([entry]) =>
      setSize(
        Math.max(
          120 + 2 * MARGIN,
          Math.floor(
            Math.min(entry.contentRect.width, entry.contentRect.height)
          )
        )
      )
    )
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  // Handles go on whatever is selected (found by ID, at any depth) -- in Select; Distort has its own
  useEffect(() => {
    const nodes =
      tool === "select"
        ? selection
            .map((id) =>
              stage.current?.findOne((node: Konva.Node) => node.id() === id)
            )
            .filter((node): node is Konva.Node => node !== undefined)
        : []
    transformer.current?.nodes(nodes)
    transformer.current?.getLayer()?.batchDraw()
  }, [selection, layers, tool])

  const ids = new Set<string>()
  const collect = (list: Layer[]) =>
    list.forEach((layer) => {
      ids.add(layer.id)
      if (layer.type === "group") {
        collect(layer.children)
      }
    })
  collect(layers)

  /** The innermost layer under the pointer, or null for the space around the frame */
  const layerAt = (target: Konva.Node): string | null => {
    for (let node: Konva.Node | null = target; node; node = node.getParent()) {
      if (ids.has(node.id())) {
        return node.id()
      }
    }
    return null
  }

  const pick = (event: Konva.KonvaEventObject<MouseEvent | TouchEvent>) => {
    if (
      event.target.getParent() instanceof Konva.Transformer ||
      event.target.hasName(HANDLE_NAME)
    ) {
      return // A resize, rotate or corner handle -- the selection stays as it is
    }
    const clicked = layerAt(event.target)
    const additive =
      "shiftKey" in event.evt &&
      (event.evt.shiftKey || event.evt.ctrlKey || event.evt.metaKey)
    if (!clicked) {
      if (!additive) {
        onSelect([])
      }
      return
    }
    if (selection.includes(clicked)) {
      return // Already selected (perhaps from the layers panel) -- keep it, so it can be dragged
    }
    const top =
      tool === "distort" ? clicked : (topLevelOf(layers, clicked) ?? clicked)
    if (additive) {
      onSelect(
        selection.includes(top)
          ? selection.filter((id) => id !== top)
          : [...selection, top]
      )
    } else {
      onSelect([top])
    }
  }

  const report = (nodes: Konva.Node[]) =>
    onTransform(
      nodes.map((node) => ({
        id: node.id(),
        transform: fromKonva({
          x: node.x(),
          y: node.y(),
          scaleX: node.scaleX(),
          scaleY: node.scaleY(),
          rotation: node.rotation(),
          skewX: node.skewX(),
          skewY: node.skewY(),
        }),
      }))
    )

  // Frame pixels to screen pixels, leaving the margin all round
  const scale = (size - 2 * MARGIN) / FRAME_SIZE

  // The pictures that get corner handles: selected ones, while distorting
  const warping =
    tool === "distort"
      ? selection
          .map((id) => findLayer(layers, id)?.layer)
          .filter(
            (layer): layer is PictureLayer =>
              layer !== undefined && isPicture(layer)
          )
      : []

  const commitWarp = () => {
    if (preview) {
      onWarp(preview.id, preview.corners)
    }
    setPreview(null)
  }

  return (
    <div
      ref={box}
      className="flex size-full min-h-0 items-center justify-center"
    >
      <Stage
        ref={stage}
        width={size}
        height={size}
        x={MARGIN}
        y={MARGIN}
        scaleX={scale}
        scaleY={scale}
        onMouseDown={pick}
        onTouchStart={pick}
      >
        {/* The layers, cut off at the frame's edge -- what the shot will show */}
        <KonvaLayer
          clipX={0}
          clipY={0}
          clipWidth={FRAME_SIZE}
          clipHeight={FRAME_SIZE}
        >
          <Rect
            width={FRAME_SIZE}
            height={FRAME_SIZE}
            fillPatternImage={checkerboard() as unknown as HTMLImageElement}
            listening={false}
          />
          {layers.map((layer) => (
            <LayerNode
              key={layer.id}
              layer={layer}
              topLevel
              selection={selection}
              tool={tool}
              preview={preview}
              imageUrl={imageUrl}
              placeholderLabel={placeholderLabel}
              onDragEnd={(node) => report([node])}
            />
          ))}
        </KonvaLayer>
        {/* Handles, over everything and free to reach into the margin */}
        <KonvaLayer>
          <Rect
            width={FRAME_SIZE}
            height={FRAME_SIZE}
            stroke="rgba(128, 128, 128, 0.5)"
            strokeWidth={1}
            strokeScaleEnabled={false}
            listening={false}
          />
          <Transformer
            ref={transformer}
            rotationSnaps={[0, 90, 180, 270]}
            ignoreStroke
            onTransformEnd={() => report(transformer.current?.nodes() ?? [])}
          />
          {warping.map((layer) => (
            <CornerHandles
              key={layer.id}
              layers={layers}
              layer={layer}
              corners={
                (preview?.id === layer.id ? preview.corners : layer.corners) ??
                UNWARPED
              }
              url={imageUrl(layer)}
              radius={6 / scale}
              onPreview={(corners) => setPreview({ id: layer.id, corners })}
              onCommit={commitWarp}
            />
          ))}
        </KonvaLayer>
      </Stage>
    </div>
  )
}

/**
 * One layer: a Konva group placed by the layer's transform, holding its content centred on (0, 0) -- so the
 * transform's x and y are the layer's centre, and it rotates and scales about its middle.
 */
function LayerNode({
  layer,
  topLevel,
  selection,
  tool,
  preview,
  imageUrl,
  placeholderLabel,
  onDragEnd,
}: {
  layer: Layer
  topLevel: boolean
  selection: string[]
  tool: Tool
  preview: Preview
  imageUrl: (layer: Layer) => string | null
  placeholderLabel: (layer: Layer) => string
  onDragEnd: (node: Konva.Node) => void
}) {
  const selected = selection.includes(layer.id)
  // Selected layers can always be dragged; other top-level ones too -- except the background (it fills the frame,
  // and would otherwise move whenever a click missed everything else), and a group with a layer selected inside it
  // (so dragging that layer moves just it, not the whole group)
  // Nothing moves while distorting -- a drag near a corner should never shift the layer instead
  const draggable =
    tool === "select" &&
    (selected ||
      (topLevel &&
        layer.type !== "background" &&
        !(
          layer.type === "group" && containsSelected(layer.children, selection)
        )))

  return (
    <Group
      id={layer.id}
      {...toKonva(layer.transform)}
      opacity={layer.opacity}
      visible={layer.visible}
      draggable={draggable}
      onDragEnd={(event) => {
        event.cancelBubble = true
        onDragEnd(event.target)
      }}
    >
      {layer.type === "group" ? (
        layer.children.map((child) => (
          <LayerNode
            key={child.id}
            layer={child}
            topLevel={false}
            selection={selection}
            tool={tool}
            preview={preview}
            imageUrl={imageUrl}
            placeholderLabel={placeholderLabel}
            onDragEnd={onDragEnd}
          />
        ))
      ) : layer.type === "text" ? (
        <TextContent layer={layer} />
      ) : (
        <PictureContent
          layer={layer}
          corners={preview?.id === layer.id ? preview.corners : layer.corners}
          url={imageUrl(layer)}
          label={placeholderLabel(layer)}
        />
      )}
    </Group>
  )
}

/**
 * True if any of these layers, at any depth, is selected.
 */
function containsSelected(layers: Layer[], selection: string[]): boolean {
  return layers.some(
    (layer) =>
      selection.includes(layer.id) ||
      (layer.type === "group" && containsSelected(layer.children, selection))
  )
}

/**
 * The size a picture is drawn at, before its transform: a background fills the frame; anything else is its image's
 * own size -- or, until it has one, its placeholder's.
 */
function pictureSize(
  layer: PictureLayer,
  image: HTMLImageElement | null
): [number, number] {
  if (layer.type === "background") {
    return [FRAME_SIZE, FRAME_SIZE]
  }
  return image ? [image.width, image.height] : PLACEHOLDER_SIZE[layer.type]
}

/** A picture's image, once it has loaded -- null before then, or if it has none */
function usePicture(url: string | null): {
  image: HTMLImageElement | null
  failed: boolean
} {
  // "anonymous" so S3 sends CORS headers -- otherwise the canvas would be "tainted" and could never be exported
  const [image, status] = useImage(url ?? "", "anonymous")
  return {
    image: url && image && status === "loaded" ? image : null,
    failed: status === "failed",
  }
}

/**
 * A layer's picture, centred and warped onto its corners if it has any -- or, until it has an image, a dashed
 * placeholder (in the same shape) saying what will go there.
 */
function PictureContent({
  layer,
  corners,
  url,
  label,
}: {
  layer: PictureLayer
  corners: Corners | null
  url: string | null
  label: string
}) {
  const { image, failed } = usePicture(url)
  const [width, height] = pictureSize(layer, image)
  const fill = layer.type === "background"

  if (image) {
    return corners ? (
      <WarpedImage
        image={image}
        width={width}
        height={height}
        corners={corners}
      />
    ) : (
      <KonvaImage
        image={image}
        width={width}
        height={height}
        offsetX={width / 2}
        offsetY={height / 2}
      />
    )
  }

  const shape = corners ?? UNWARPED
  const middle = squareToQuad(shape)(0.5, 0.5)
  return (
    <>
      <Line
        points={CORNER_NAMES.flatMap((name) => [
          (shape[name].x - 0.5) * width,
          (shape[name].y - 0.5) * height,
        ])}
        closed
        fill={fill ? "#f1f1f1" : "rgba(120, 120, 120, 0.12)"}
        stroke="#9a9a9a"
        strokeWidth={2}
        dash={[12, 8]}
      />
      <Text
        text={failed ? `${label}\n(image failed to load)` : label}
        x={(middle.x - 0.5) * width}
        y={(middle.y - 0.5) * height}
        width={width - 24}
        offsetX={width / 2 - 12}
        offsetY={14}
        align="center"
        fontSize={fill ? 28 : 22}
        fontFamily={FONT_FAMILIES.sans}
        fill="#6b6b6b"
        listening={false}
      />
    </>
  )
}

/**
 * A picture warped onto its corners. It's drawn once into an offscreen canvas (again only when the image or corners
 * change), so moving the layer around costs no more than an ordinary image. Clicks land only inside the warped shape,
 * not anywhere in the box around it.
 */
function WarpedImage({
  image,
  width,
  height,
  corners,
}: {
  image: HTMLImageElement
  width: number
  height: number
  corners: Corners
}) {
  const bounds = warpedBounds(corners, width, height)
  const canvas = useMemo(() => {
    const box = warpedBounds(corners, width, height)
    const scale = Math.min(1, MAX_WARP_SIZE / Math.max(box.width, box.height))
    const offscreen = document.createElement("canvas")
    offscreen.width = Math.max(1, Math.ceil(box.width * scale))
    offscreen.height = Math.max(1, Math.ceil(box.height * scale))
    const context = offscreen.getContext("2d")!
    context.setTransform(scale, 0, 0, scale, -box.x * scale, -box.y * scale)
    drawWarped(context, image, width, height, corners)
    return offscreen
  }, [image, width, height, corners])

  return (
    <KonvaImage
      image={canvas}
      x={bounds.x - width / 2}
      y={bounds.y - height / 2}
      width={bounds.width}
      height={bounds.height}
      hitFunc={(context, shape) => {
        context.beginPath()
        CORNER_NAMES.forEach((name, i) => {
          const x = corners[name].x * width - bounds.x
          const y = corners[name].y * height - bounds.y
          if (i === 0) {
            context.moveTo(x, y)
          } else {
            context.lineTo(x, y)
          }
        })
        context.closePath()
        context.fillStrokeShape(shape)
      }}
    />
  )
}

/**
 * Distort's handles for one picture: its outline, and a handle on each corner. They're drawn above every layer, in
 * frame space (worked out from the layer's transform and its groups'), so they stay the same size however the
 * picture is scaled or skewed. A corner can't be dragged anywhere that would fold the picture -- it stops instead.
 */
function CornerHandles({
  layers,
  layer,
  corners,
  url,
  radius,
  onPreview,
  onCommit,
}: {
  layers: Layer[]
  layer: PictureLayer
  corners: Corners
  url: string | null
  /** Handle radius, in frame pixels */
  radius: number
  onPreview: (corners: Corners) => void
  onCommit: () => void
}) {
  const { image } = usePicture(url)
  const [width, height] = pictureSize(layer, image)
  const matrix = frameMatrixOf(layers, layer)
  const at = (name: CornerName) =>
    apply(matrix, {
      x: (corners[name].x - 0.5) * width,
      y: (corners[name].y - 0.5) * height,
    })
  const points = CORNER_NAMES.map(at)

  const drag = (name: CornerName, index: number, node: Konva.Node) => {
    const local = apply(invert(matrix), node.position())
    const next = {
      ...corners,
      [name]: { x: local.x / width + 0.5, y: local.y / height + 0.5 },
    }
    if (isConvex(next, MIN_CORNER_ANGLE)) {
      onPreview(next)
    } else {
      node.position(points[index])
    }
  }

  return (
    <>
      <Line
        points={points.flatMap((p) => [p.x, p.y])}
        closed
        stroke={HANDLE_COLOUR}
        strokeWidth={1.5}
        strokeScaleEnabled={false}
        listening={false}
      />
      {CORNER_NAMES.map((name, index) => (
        <Circle
          key={name}
          name={HANDLE_NAME}
          x={points[index].x}
          y={points[index].y}
          radius={radius}
          fill="white"
          stroke={HANDLE_COLOUR}
          strokeWidth={1.5}
          strokeScaleEnabled={false}
          draggable
          onMouseEnter={(event) => {
            const container = event.target.getStage()?.container()
            if (container) {
              container.style.cursor = "move"
            }
          }}
          onMouseLeave={(event) => {
            const container = event.target.getStage()?.container()
            if (container) {
              container.style.cursor = ""
            }
          }}
          onDragMove={(event) => drag(name, index, event.target)}
          onDragEnd={(event) => {
            event.cancelBubble = true
            onCommit()
          }}
        />
      ))}
    </>
  )
}

/**
 * A text layer, centred on its position. Konva measures the text first, so it can be centred whatever it says.
 */
function TextContent({ layer }: { layer: Extract<Layer, { type: "text" }> }) {
  const config = {
    text: layer.text || " ",
    fontSize: layer.size,
    fontFamily: FONT_FAMILIES[layer.font],
    align: layer.align,
  }
  const measured = new Konva.Text(config)
  const width = measured.width()
  const height = measured.height()
  measured.destroy()
  return (
    <Text
      {...config}
      fill={layer.colour}
      width={width}
      offsetX={width / 2}
      offsetY={height / 2}
    />
  )
}
