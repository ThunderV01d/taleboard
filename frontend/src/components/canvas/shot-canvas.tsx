import Konva from "konva"
import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type Ref,
} from "react"
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

import type { Pen, Tool } from "@/components/canvas/tool-strip"
import {
  finishStroke,
  strokeBounds,
  warpStrokes,
  type Bounds,
  type FreehandLayer,
  type Stroke,
} from "@/lib/freehand"
import { useLoadedImage } from "@/lib/images"
import { FONT_FAMILIES } from "@/lib/labels"
import {
  apply,
  findLayer,
  FRAME_SIZE,
  frameMatrixOf,
  fromKonva,
  invert,
  SHOT_FRAME,
  toKonva,
  topLevelOf,
  type Frame,
  type Layer,
  type Transform,
} from "@/lib/layers"
import { clampPan, zoomAt, type View } from "@/lib/zoom"
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

/** What the canvas can do when asked from outside */
export type CanvasHandle = {
  /** What the frame shows, as a PNG the frame's size -- on white paper, without the selection or the checkerboard */
  flatten: () => Promise<Blob>
}

/** A picture's (or drawing's) corners while one is being dragged in Distort -- drawn, but not an edit until the drag ends */
type Preview = { id: string; corners: Corners } | null

/** A stroke being drawn: the drawing it goes into (null for a new one), its path in that drawing's space and in the frame's */
type Drawing = {
  target: string | null
  local: number[]
  frame: number[]
} | null

/** A layer Distort can warp: a picture (its corners), or a drawing (its strokes' points) */
type Warpable = PictureLayer | FreehandLayer

/**
 * A shot's (or sketch's) frame, drawn with Konva: every layer in its place, groups nested, bottom to top.
 *
 * Click a layer to select it (a layer inside a group selects the whole group -- pick it from the layers panel to
 * select just it); shift-click adds to the selection. Selected layers get handles to move, resize and rotate them.
 * Konva does the dragging; the result is reported once, when the drag or resize ends, so each is one undo step.
 *
 * With the Distort tool, selected pictures and drawings get a handle on each corner instead, to warp their perspective
 * (a drawing's strokes are warped point by point). A click then picks the layer itself, even inside a group (groups
 * can't be distorted), and nothing moves when dragged.
 *
 * With the brush, a drag draws a stroke into the selected drawing -- or, if no drawing is selected, a new one; with
 * the eraser, into the selected drawing only, rubbing out its own strokes. Each stroke is reported once it's finished,
 * so it's one undo step.
 *
 * The view zooms and pans (see lib/zoom.ts): Ctrl and the wheel zoom about the pointer, the wheel on its own pans, and
 * so does dragging with Space held (or the middle button). The canvas stays the size of its space throughout.
 */
export function ShotCanvas({
  ref,
  frame = SHOT_FRAME,
  layers,
  selection,
  tool,
  pen,
  imageUrl,
  placeholderLabel,
  onSelect,
  onTransform,
  onWarp,
  onWarpStrokes,
  onStroke,
  view,
  onView,
  onFitScale,
  scaleLocked = false,
  readOnly = false,
}: {
  ref?: Ref<CanvasHandle>
  /** The frame's size (default: a shot's) */
  frame?: Frame
  layers: Layer[]
  selection: string[]
  tool: Tool
  /** What the brush and eraser draw with */
  pen: Pen
  /** The URL to draw a layer's image from, if it has one */
  imageUrl: (layer: Layer) => string | null
  /** What a not-yet-drawn layer's placeholder says */
  placeholderLabel: (layer: Layer) => string
  onSelect: (ids: string[]) => void
  onTransform: (changes: TransformChange[]) => void
  /** A picture's new corners, once a corner has been dragged */
  onWarp: (id: string, corners: Corners) => void
  /** A drawing's strokes, warped, once a corner has been dragged */
  onWarpStrokes: (id: string, strokes: Stroke[]) => void
  /** A finished stroke, for the drawing it goes into (null: a new drawing, centred on the frame) */
  onStroke: (target: string | null, stroke: Stroke) => void
  /** How far it's zoomed and panned */
  view: View
  onView: (view: View) => void
  /** The scale (screen pixels per frame pixel) that fits the frame in its space -- reported whenever it changes */
  onFitScale?: (scale: number) => void
  /** Whether layers are resized keeping their shape (corner handles only) */
  scaleLocked?: boolean
  /** Selecting only -- nothing moves, and the selection has no handles (a project shared to view) */
  readOnly?: boolean
}) {
  const box = useRef<HTMLDivElement>(null)
  const stage = useRef<Konva.Stage>(null)
  const transformer = useRef<Konva.Transformer>(null)
  const content = useRef<Konva.Layer>(null)
  const checker = useRef<Konva.Rect>(null)
  const [space, setSpace] = useState({ width: 600, height: 600 })
  const [preview, setPreview] = useState<Preview>(null)
  const [drawing, setDrawing] = useState<Drawing>(null)
  // Space held (to pan by dragging), and a pan drag under way: where it started, and the view then
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [panning, setPanning] = useState<{
    x: number
    y: number
    view: View
  } | null>(null)

  useEffect(() => {
    const typing = (event: KeyboardEvent) =>
      (event.target as HTMLElement).closest(
        "input, textarea, select, [contenteditable=true], [role=dialog], [role=menu], [role=listbox], [role=checkbox]"
      )
    const down = (event: KeyboardEvent) => {
      if (event.code === "Space" && !typing(event)) {
        event.preventDefault() // Not a page scroll, nor a click on a focused button
        setSpaceHeld(true)
      }
    }
    const up = (event: KeyboardEvent) => {
      if (event.code === "Space") {
        setSpaceHeld(false)
      }
    }
    const blur = () => setSpaceHeld(false)
    window.addEventListener("keydown", down)
    window.addEventListener("keyup", up)
    window.addEventListener("blur", blur)
    return () => {
      window.removeEventListener("keydown", down)
      window.removeEventListener("keyup", up)
      window.removeEventListener("blur", blur)
    }
  }, [])

  // The canvas fills the space it's given; the frame is fitted to it (keeping its shape), then zoomed and panned
  useEffect(() => {
    const element = box.current
    if (!element) {
      return
    }
    const observer = new ResizeObserver(([entry]) =>
      setSpace({
        width: Math.max(120 + 2 * MARGIN, Math.floor(entry.contentRect.width)),
        height: Math.max(
          120 + 2 * MARGIN,
          Math.floor(entry.contentRect.height)
        ),
      })
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

  // Frame pixels to screen pixels: fitted to the space (leaving the margin all round), then zoomed
  const fit = Math.min(
    (space.width - 2 * MARGIN) / frame.width,
    (space.height - 2 * MARGIN) / frame.height
  )
  const scale = fit * view.zoom
  // Where the frame's top-left corner is on the canvas: centred, then panned
  const origin = {
    x: (space.width - frame.width * scale) / 2 + view.x,
    y: (space.height - frame.height * scale) / 2 + view.y,
  }
  useEffect(() => onFitScale?.(fit), [fit, onFitScale])

  /** A new view, with the frame kept within reach */
  const moveTo = (next: View) =>
    onView(
      clampPan(
        next,
        {
          width: frame.width * fit * next.zoom,
          height: frame.height * fit * next.zoom,
        },
        space
      )
    )

  /** The pointer, in screen pixels from the middle of the canvas -- what zoomAt zooms about */
  const fromMiddle = () => {
    const at = stage.current?.getPointerPosition()
    return at
      ? { x: at.x - space.width / 2, y: at.y - space.height / 2 }
      : undefined
  }

  const wheel = (event: Konva.KonvaEventObject<WheelEvent>) => {
    event.evt.preventDefault()
    if (event.evt.ctrlKey || event.evt.metaKey) {
      // Ctrl and the wheel (or a trackpad pinch, which arrives as one) zoom about the pointer
      moveTo(
        zoomAt(
          view,
          view.zoom * Math.exp(-event.evt.deltaY * 0.002),
          fromMiddle()
        )
      )
    } else {
      moveTo({
        ...view,
        x: view.x - event.evt.deltaX,
        y: view.y - event.evt.deltaY,
      })
    }
  }

  useImperativeHandle(
    ref,
    () => ({
      flatten: async () => {
        const layer = content.current
        if (!layer) {
          throw new Error("The canvas isn't ready yet.")
        }
        // Just the frame, at its own size: the margin left out, and screen pixels scaled back up to frame pixels
        checker.current?.hide()
        let pixels: HTMLCanvasElement
        try {
          pixels = layer.toCanvas({
            x: origin.x,
            y: origin.y,
            width: frame.width * scale,
            height: frame.height * scale,
            pixelRatio: 1 / scale,
          })
        } finally {
          checker.current?.show()
          layer.batchDraw()
        }
        // On white, as if drawn on paper -- an empty part of the frame then reads as background, not black
        const paper = document.createElement("canvas")
        paper.width = frame.width
        paper.height = frame.height
        const context = paper.getContext("2d")!
        context.fillStyle = "#ffffff"
        context.fillRect(0, 0, frame.width, frame.height)
        context.drawImage(pixels, 0, 0, frame.width, frame.height)
        return new Promise<Blob>((resolve, reject) =>
          paper.toBlob(
            (blob) =>
              blob
                ? resolve(blob)
                : reject(new Error("The drawing couldn't be saved as a PNG.")),
            "image/png"
          )
        )
      },
    }),
    [frame, scale, origin.x, origin.y]
  )

  // The pictures and drawings that get corner handles: selected ones, while distorting (a drawing with nothing in it has no corners)
  const warping =
    tool === "distort"
      ? selection
          .map((id) => findLayer(layers, id)?.layer)
          .filter(
            (layer): layer is Warpable =>
              layer !== undefined &&
              (isPicture(layer) ||
                (layer.type === "freehand" &&
                  strokeBounds(layer.strokes) !== null))
          )
      : []

  const commitWarp = () => {
    const layer = preview && findLayer(layers, preview.id)?.layer
    if (preview && layer?.type === "freehand") {
      const bounds = strokeBounds(layer.strokes)
      if (bounds) {
        onWarpStrokes(
          layer.id,
          warpStrokes(layer.strokes, bounds, preview.corners)
        )
      }
    } else if (preview) {
      onWarp(preview.id, preview.corners)
    }
    setPreview(null)
  }

  // The drawing the brush or eraser works in: the selected one, if a drawing is selected (the brush starts a new one
  // otherwise; the eraser has nothing to rub out)
  const selectedDrawing =
    selection.length === 1
      ? (() => {
          const layer = findLayer(layers, selection[0])?.layer
          return layer?.type === "freehand" ? layer : null
        })()
      : null
  const drawingTool = tool === "brush" || tool === "eraser"

  /** Where the pointer is, in the frame and in the target drawing's own space (centred on the frame, for a new one) */
  const pointer = (target: FreehandLayer | null) => {
    const at = stage.current?.getRelativePointerPosition()
    if (!at) {
      return null
    }
    const local = target
      ? apply(invert(frameMatrixOf(layers, target)), at)
      : { x: at.x - frame.width / 2, y: at.y - frame.height / 2 }
    return { frame: at, local }
  }

  const startStroke = () => {
    if (tool === "eraser" && !selectedDrawing) {
      return // Nothing to rub out
    }
    const at = pointer(selectedDrawing)
    if (at) {
      setDrawing({
        target: selectedDrawing?.id ?? null,
        local: [at.local.x, at.local.y],
        frame: [at.frame.x, at.frame.y],
      })
    }
  }

  const extendStroke = () => {
    if (!drawing) {
      return
    }
    const at = pointer(selectedDrawing)
    if (at) {
      setDrawing({
        ...drawing,
        local: [...drawing.local, at.local.x, at.local.y],
        frame: [...drawing.frame, at.frame.x, at.frame.y],
      })
    }
  }

  // A stroke's width is kept in its drawing's own pixels, so the pen draws the same width on screen however the drawing is scaled
  const drawingScale = (target: FreehandLayer | null) => {
    if (!target) {
      return 1
    }
    const [a, b, c, d] = frameMatrixOf(layers, target)
    return Math.sqrt(Math.abs(a * d - b * c)) || 1
  }

  const endStroke = () => {
    if (!drawing) {
      return
    }
    const points = finishStroke(drawing.local)
    if (points.length > 0) {
      onStroke(drawing.target, {
        points,
        colour: pen.colour,
        width:
          Math.round((pen.width / drawingScale(selectedDrawing)) * 10) / 10,
        erase: tool === "eraser",
      })
    }
    setDrawing(null)
  }

  const startPan = (event: Konva.KonvaEventObject<MouseEvent>) => {
    setPanning({ x: event.evt.clientX, y: event.evt.clientY, view })
  }

  const mouseDown = (event: Konva.KonvaEventObject<MouseEvent>) => {
    if (spaceHeld || event.evt.button === 1) {
      event.evt.preventDefault() // The middle button would otherwise start the browser's own scrolling
      startPan(event)
    } else if (drawingTool) {
      startStroke()
    } else {
      pick(event)
    }
  }

  const mouseMove = (event: Konva.KonvaEventObject<MouseEvent>) => {
    if (panning) {
      moveTo({
        ...panning.view,
        x: panning.view.x + event.evt.clientX - panning.x,
        y: panning.view.y + event.evt.clientY - panning.y,
      })
    } else {
      extendStroke()
    }
  }

  const mouseUp = () => {
    if (panning) {
      setPanning(null)
    } else {
      endStroke()
    }
  }

  return (
    <div ref={box} className="relative size-full min-h-0 overflow-hidden">
      <Stage
        ref={stage}
        width={space.width}
        height={space.height}
        x={origin.x}
        y={origin.y}
        scaleX={scale}
        scaleY={scale}
        // Placed over the space rather than in it, so the canvas never changes the size it's measured from
        style={{
          position: "absolute",
          inset: 0,
          cursor: panning
            ? "grabbing"
            : spaceHeld
              ? "grab"
              : drawingTool
                ? "crosshair"
                : undefined,
        }}
        onMouseDown={mouseDown}
        onTouchStart={drawingTool ? startStroke : pick}
        onMouseMove={mouseMove}
        onTouchMove={extendStroke}
        onMouseUp={mouseUp}
        onTouchEnd={endStroke}
        onMouseLeave={mouseUp}
        onWheel={wheel}
      >
        {/* The layers, cut off at the frame's edge -- what the shot will show */}
        <KonvaLayer
          ref={content}
          clipX={0}
          clipY={0}
          clipWidth={frame.width}
          clipHeight={frame.height}
        >
          <Rect
            ref={checker}
            width={frame.width}
            height={frame.height}
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
              movable={!spaceHeld && !readOnly}
              onDragEnd={(node) => report([node])}
            />
          ))}
        </KonvaLayer>
        {/* Handles, over everything and free to reach into the margin */}
        <KonvaLayer>
          <Rect
            width={frame.width}
            height={frame.height}
            stroke="rgba(128, 128, 128, 0.5)"
            strokeWidth={1}
            strokeScaleEnabled={false}
            listening={false}
          />
          <Transformer
            ref={transformer}
            rotationSnaps={[0, 90, 180, 270]}
            // Locked: only the corners, which keep a layer's shape as it's resized
            keepRatio
            enabledAnchors={
              readOnly
                ? []
                : scaleLocked
                  ? ["top-left", "top-right", "bottom-left", "bottom-right"]
                  : undefined
            }
            rotateEnabled={!readOnly}
            ignoreStroke
            onTransformEnd={() => report(transformer.current?.nodes() ?? [])}
          />
          {warping.map((layer) => (
            <CornerHandles
              key={layer.id}
              layers={layers}
              layer={layer}
              corners={
                (preview?.id === layer.id
                  ? preview.corners
                  : layer.type === "freehand"
                    ? null
                    : layer.corners) ?? UNWARPED
              }
              url={layer.type === "freehand" ? null : imageUrl(layer)}
              radius={6 / scale}
              onPreview={(corners) => setPreview({ id: layer.id, corners })}
              onCommit={commitWarp}
            />
          ))}
          {/* The stroke being drawn, until it's finished and kept */}
          {drawing && (
            <Line
              points={drawing.frame}
              stroke={
                tool === "eraser" ? "rgba(128, 128, 128, 0.5)" : pen.colour
              }
              strokeWidth={pen.width}
              lineCap="round"
              lineJoin="round"
              listening={false}
            />
          )}
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
  movable,
  onDragEnd,
}: {
  layer: Layer
  topLevel: boolean
  selection: string[]
  tool: Tool
  preview: Preview
  imageUrl: (layer: Layer) => string | null
  placeholderLabel: (layer: Layer) => string
  /** False while Space is held -- a drag then pans the view instead */
  movable: boolean
  onDragEnd: (node: Konva.Node) => void
}) {
  const selected = selection.includes(layer.id)
  // Selected layers can always be dragged; other top-level ones too -- except the background (it fills the frame,
  // and would otherwise move whenever a click missed everything else), and a group with a layer selected inside it
  // (so dragging that layer moves just it, not the whole group)
  // Nothing moves while distorting -- a drag near a corner should never shift the layer instead
  const draggable =
    movable &&
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
            movable={movable}
            onDragEnd={onDragEnd}
          />
        ))
      ) : layer.type === "text" ? (
        <TextContent layer={layer} />
      ) : layer.type === "freehand" ? (
        <FreehandContent
          layer={layer}
          corners={preview?.id === layer.id ? preview.corners : null}
        />
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
 * The size a picture is drawn at, before its transform: a background fills the (shot's) frame; anything else is its
 * image's own size -- or, until it has one, its placeholder's.
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
  const { image, failed } = useLoadedImage(url)
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
  layer: Warpable
  corners: Corners
  url: string | null
  /** Handle radius, in frame pixels */
  radius: number
  onPreview: (corners: Corners) => void
  onCommit: () => void
}) {
  const { image } = useLoadedImage(url)
  // The box the corners are fractions of: a picture's own, centred on its middle; a drawing's strokes' bounds
  const box: Bounds =
    layer.type === "freehand"
      ? (strokeBounds(layer.strokes) ?? { x: 0, y: 0, width: 1, height: 1 })
      : (() => {
          const [width, height] = pictureSize(layer, image)
          return { x: -width / 2, y: -height / 2, width, height }
        })()
  const matrix = frameMatrixOf(layers, layer)
  const at = (name: CornerName) =>
    apply(matrix, {
      x: box.x + corners[name].x * box.width,
      y: box.y + corners[name].y * box.height,
    })
  const points = CORNER_NAMES.map(at)

  const drag = (name: CornerName, index: number, node: Konva.Node) => {
    const local = apply(invert(matrix), node.position())
    const next = {
      ...corners,
      [name]: {
        x: (local.x - box.x) / box.width,
        y: (local.y - box.y) / box.height,
      },
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
 * A drawing: its strokes, in order, in its own space. A drawing with erasing strokes is drawn to its own canvas first
 * (Konva's cache), so they rub out its earlier strokes and nothing beneath it. While a corner is dragged in Distort,
 * the strokes are drawn warped.
 */
function FreehandContent({
  layer,
  corners,
}: {
  layer: FreehandLayer
  corners: Corners | null
}) {
  const group = useRef<Konva.Group>(null)
  const strokes = useMemo(() => {
    const bounds = corners && strokeBounds(layer.strokes)
    return bounds ? warpStrokes(layer.strokes, bounds, corners) : layer.strokes
  }, [layer.strokes, corners])
  const erasing = strokes.some((stroke) => stroke.erase)

  useEffect(() => {
    const node = group.current
    if (!node) {
      return
    }
    if (erasing) {
      // At least as sharp as the frame's own pixels, so a flattened sketch is as crisp as the drawing
      const absolute = node.getAbsoluteScale()
      const inFrame =
        Math.max(Math.abs(absolute.x), Math.abs(absolute.y)) /
        (node.getStage()?.scaleX() || 1)
      node.cache({
        pixelRatio:
          Math.max(window.devicePixelRatio || 1, 1) * Math.max(inFrame, 1),
      })
    } else {
      node.clearCache()
    }
    node.getLayer()?.batchDraw()
  }, [strokes, erasing, layer.transform])

  return (
    <Group ref={group}>
      {strokes.map((stroke, index) => (
        <Line
          key={index}
          points={stroke.points}
          stroke={stroke.colour}
          strokeWidth={stroke.width}
          lineCap="round"
          lineJoin="round"
          globalCompositeOperation={
            stroke.erase ? "destination-out" : "source-over"
          }
          hitStrokeWidth={Math.max(stroke.width, 12)}
          listening={!stroke.erase}
        />
      ))}
    </Group>
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
