import {
  FlipHorizontal2Icon,
  FlipVertical2Icon,
  ImageUpIcon,
  Link2Icon,
  LoaderCircleIcon,
  RotateCcwIcon,
  SparklesIcon,
  Unlink2Icon,
  VectorSquareIcon,
} from "lucide-react"
import { useRef } from "react"

import { NumberField } from "@/components/canvas/number-field"
import { EnumSelect } from "@/components/enum-select"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  ALIGN_LABELS,
  ANGLE_LABELS,
  FACING_LABELS,
  FONT_LABELS,
  LAYER_TYPE_LABELS,
  ORIENTATION_LABELS,
  SHOT_SIZE_LABELS,
} from "@/lib/labels"
import type { LayerProgress } from "@/lib/generation"
import { placedAt, type Layer, type Transform } from "@/lib/layers"
import type { Character, Prop } from "@/lib/registries"
import type { ShotFields } from "@/lib/shots"
import { changesText, type Freshness } from "@/lib/staleness"
import { cn } from "@/lib/utils"
import { isPicture } from "@/lib/warp"

/**
 * A change to one layer. `field` names what changed, so a run of changes to one field (typing, dragging a slider) is
 * a single undo step; leave it out for one-off actions like a flip, which are always their own step.
 */
export type LayerEdit = (
  change: (layer: Layer) => Layer,
  field?: string
) => void

/**
 * The selected layer's properties (the top half of the right-hand panel): the shared ones -- name, position, size,
 * rotation, skew, flips, opacity -- and those of its type. Visibility is the eye in the layers panel.
 *
 * Generated layers show what they were drawn from (location and facing; character or prop and orientation), whether
 * their picture is up to date (and if not, what's changed since it was drawn), and a button to draw them -- or draw
 * them again, once something they're drawn from has changed -- with where that's up to.
 */
export function LayerProperties({
  selected,
  selectionCount,
  characters,
  props,
  locationName,
  onEditLayer,
  onReplaceImage,
  onDistort,
  progress,
  freshness,
  unsaved,
  scaleLocked,
  onScaleLocked,
  onGenerate,
  readOnly = false,
}: {
  /** The selected layer, when exactly one is selected */
  selected: Layer | null
  selectionCount: number
  characters: Character[]
  props: Prop[]
  locationName: string
  onEditLayer: LayerEdit
  onReplaceImage: (file: File) => void
  /** Switches to the Distort tool */
  onDistort: () => void
  /** Where the selected layer stands with generation, if anywhere */
  progress?: LayerProgress
  /** Whether the selected layer's picture is up to date (null for a layer that isn't generated) */
  freshness: Freshness | null
  /** Whether there are edits not saved yet -- the server hasn't said whether they put the layer out of date */
  unsaved: boolean
  /** Whether width and height scale together (the chain link) */
  scaleLocked: boolean
  onScaleLocked: (locked: boolean) => void
  /** Asks for a generated layer to be drawn */
  onGenerate: (layerId: string) => void
  /** Showing only -- no buttons that change, upload or draw (the fields themselves are disabled by a fieldset around this) */
  readOnly?: boolean
}) {
  if (selectionCount > 1) {
    return (
      <p className="text-sm text-muted-foreground">
        {selectionCount} layers selected. Move or resize them together on the
        canvas.
      </p>
    )
  }
  if (!selected) {
    return (
      <p className="text-sm text-muted-foreground">
        No layer selected. Click one on the canvas or in the layers panel.
      </p>
    )
  }

  const layer = selected
  const set = <K extends keyof Transform>(key: K, value: Transform[K]) =>
    onEditLayer(
      (l) => ({ ...l, transform: { ...l.transform, [key]: value } }),
      `transform.${key}`
    )

  // Locked, the other scale follows in proportion (keeping a flip); a 0 is passed over, as it would lose the shape --
  // it's usually on the way to typing "0.5"
  const setScale = (axis: "x" | "y", value: number) =>
    onEditLayer((l) => {
      const { scale_x, scale_y } = l.transform
      const [mine, other] =
        axis === "x" ? [scale_x, scale_y] : [scale_y, scale_x]
      if (!scaleLocked) {
        return { ...l, transform: { ...l.transform, [`scale_${axis}`]: value } }
      }
      if (value === 0 || mine === 0) {
        return l
      }
      const follows = other * (value / mine)
      return {
        ...l,
        transform: {
          ...l.transform,
          scale_x: axis === "x" ? value : follows,
          scale_y: axis === "y" ? value : follows,
        },
      }
    }, `transform.scale_${axis}`)

  return (
    <div className="space-y-5">
      <Section title={LAYER_TYPE_LABELS[layer.type]}>
        <div className="space-y-1">
          <Label htmlFor="layer-name" className="text-xs text-muted-foreground">
            Name
          </Label>
          <Input
            id="layer-name"
            className="h-8"
            maxLength={100}
            value={layer.name}
            onChange={(e) =>
              onEditLayer((l) => ({ ...l, name: e.target.value }), "name")
            }
          />
        </div>
        <TypeProperties
          layer={layer}
          characters={characters}
          props={props}
          locationName={locationName}
          onEditLayer={onEditLayer}
          onReplaceImage={onReplaceImage}
          readOnly={readOnly}
        />
      </Section>

      {(layer.type === "background" ||
        layer.type === "character" ||
        layer.type === "prop") && (
        <Section title="Picture">
          <GenerateControls
            freshness={freshness ?? { state: "undrawn" }}
            unsaved={unsaved}
            progress={progress}
            onGenerate={() => onGenerate(layer.id)}
            readOnly={readOnly}
          />
        </Section>
      )}

      <Section title="Placement">
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            id="t-x"
            label="X (centre)"
            value={layer.transform.x}
            onChange={(v) => set("x", v)}
          />
          <NumberField
            id="t-y"
            label="Y (centre)"
            value={layer.transform.y}
            onChange={(v) => set("y", v)}
          />
          <div className="col-span-2 grid grid-cols-[1fr_auto_1fr] items-end gap-1">
            <NumberField
              id="t-sx"
              label="Width scale"
              value={layer.transform.scale_x}
              step={0.05}
              decimals={2}
              onChange={(v) => setScale("x", v)}
            />
            <Button
              variant="ghost"
              size="icon-sm"
              className={cn("mb-0.5", scaleLocked && "text-primary")}
              aria-label="Keep width and height scale together"
              aria-pressed={scaleLocked}
              title={
                scaleLocked
                  ? "Width and height scale together -- click to set them separately"
                  : "Width and height scale separately -- click to keep them together"
              }
              onClick={() => onScaleLocked(!scaleLocked)}
            >
              {scaleLocked ? <Link2Icon /> : <Unlink2Icon />}
            </Button>
            <NumberField
              id="t-sy"
              label="Height scale"
              value={layer.transform.scale_y}
              step={0.05}
              decimals={2}
              onChange={(v) => setScale("y", v)}
            />
          </div>
          <NumberField
            id="t-r"
            label="Rotation (°)"
            value={layer.transform.rotation}
            onChange={(v) => set("rotation", v)}
          />
          <div />
          <NumberField
            id="t-kx"
            label="Skew X (°)"
            value={layer.transform.skew_x}
            min={-80}
            max={80}
            onChange={(v) => set("skew_x", Math.max(-80, Math.min(80, v)))}
          />
          <NumberField
            id="t-ky"
            label="Skew Y (°)"
            value={layer.transform.skew_y}
            min={-80}
            max={80}
            onChange={(v) => set("skew_y", Math.max(-80, Math.min(80, v)))}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              onEditLayer((l) => ({
                ...l,
                transform: { ...l.transform, scale_x: -l.transform.scale_x },
              }))
            }
          >
            <FlipHorizontal2Icon />
            Flip
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              onEditLayer((l) => ({
                ...l,
                transform: { ...l.transform, scale_y: -l.transform.scale_y },
              }))
            }
          >
            <FlipVertical2Icon />
            Flip vertically
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              onEditLayer((l) => ({
                ...l,
                transform: placedAt(l.transform.x, l.transform.y),
              }))
            }
          >
            <RotateCcwIcon />
            Reset
          </Button>
        </div>
      </Section>

      {isPicture(layer) && (
        <Section title="Perspective">
          <p className="text-xs text-muted-foreground">
            {layer.corners
              ? "Corners moved. Drag them with the Distort tool."
              : "Not distorted. Drag its corners with the Distort tool to fix its perspective."}
          </p>
          <div className="flex flex-wrap gap-2" hidden={readOnly}>
            <Button variant="outline" size="sm" onClick={onDistort}>
              <VectorSquareIcon />
              Distort (D)
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={!layer.corners}
              onClick={() => onEditLayer((l) => ({ ...l, corners: null }))}
            >
              <RotateCcwIcon />
              Reset corners
            </Button>
          </div>
        </Section>
      )}

      <Section title="Appearance">
        <div className="space-y-1">
          <Label
            htmlFor="layer-opacity"
            className="text-xs text-muted-foreground"
          >
            Opacity -- {Math.round(layer.opacity * 100)}%
          </Label>
          <input
            id="layer-opacity"
            type="range"
            min={0}
            max={1}
            step={0.01}
            className="w-full accent-primary"
            value={layer.opacity}
            onChange={(e) =>
              onEditLayer(
                (l) => ({ ...l, opacity: Number(e.target.value) }),
                "opacity"
              )
            }
          />
        </div>
      </Section>
    </div>
  )
}

/**
 * A titled group of fields.
 */
function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

/**
 * The shot's own fields (the bottom half of the right-hand panel) -- always shown, whatever is selected.
 */
export function ShotProperties({
  fields,
  onEdit,
}: {
  fields: ShotFields
  onEdit: (change: Partial<ShotFields>, field: string) => void
}) {
  return (
    <Section title="Shot">
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label htmlFor="shot-size" className="text-xs text-muted-foreground">
            Size
          </Label>
          <EnumSelect
            id="shot-size"
            value={fields.shot_size}
            labels={SHOT_SIZE_LABELS}
            onChange={(shot_size) => onEdit({ shot_size }, "shot_size")}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="shot-angle" className="text-xs text-muted-foreground">
            Angle
          </Label>
          <EnumSelect
            id="shot-angle"
            value={fields.angle}
            labels={ANGLE_LABELS}
            onChange={(angle) => onEdit({ angle }, "angle")}
          />
        </div>
      </div>
      <NumberField
        id="shot-duration"
        label="Length (seconds)"
        value={fields.duration_s}
        step={0.5}
        min={0.1}
        max={60}
        onChange={(v) =>
          v > 0 && v <= 60 && onEdit({ duration_s: v }, "duration_s")
        }
      />
      <div className="space-y-1">
        <Label htmlFor="shot-details" className="text-xs text-muted-foreground">
          Details in the location
        </Label>
        <Input
          id="shot-details"
          className="h-8"
          maxLength={150}
          value={fields.details}
          onChange={(e) => onEdit({ details: e.target.value }, "details")}
        />
      </div>
      <div className="space-y-1">
        <Label
          htmlFor="shot-description"
          className="text-xs text-muted-foreground"
        >
          Description (not drawn)
        </Label>
        <Textarea
          id="shot-description"
          rows={4}
          maxLength={2000}
          value={fields.description}
          onChange={(e) =>
            onEdit({ description: e.target.value }, "description")
          }
        />
      </div>
    </Section>
  )
}

/**
 * The fields only one layer type has.
 */
function TypeProperties({
  layer,
  characters,
  props,
  locationName,
  onEditLayer,
  onReplaceImage,
  readOnly,
}: {
  layer: Layer
  characters: Character[]
  props: Prop[]
  locationName: string
  onEditLayer: LayerEdit
  onReplaceImage: (file: File) => void
  readOnly: boolean
}) {
  const file = useRef<HTMLInputElement>(null)

  switch (layer.type) {
    case "background":
      return (
        <>
          <ReadOnly
            label="Location"
            value={`${locationName} (set by the scene)`}
          />
          <Field label="Facing" id="bg-facing">
            <EnumSelect
              id="bg-facing"
              value={layer.facing}
              labels={FACING_LABELS}
              onChange={(facing) =>
                onEditLayer((l) => ({ ...l, facing }), "facing")
              }
            />
          </Field>
        </>
      )
    case "character":
      return (
        <>
          <ReadOnly
            label="Character"
            value={
              characters.find((c) => c.id === layer.character_id)?.name ??
              layer.character_id
            }
          />
          <Field label="Orientation" id="char-orientation">
            <EnumSelect
              id="char-orientation"
              value={layer.orientation}
              labels={ORIENTATION_LABELS}
              onChange={(orientation) =>
                onEditLayer((l) => ({ ...l, orientation }), "orientation")
              }
            />
          </Field>
          <Field label="Action" id="char-action">
            <Textarea
              id="char-action"
              rows={2}
              maxLength={200}
              placeholder="eg:- waving from the doorway"
              value={layer.action}
              onChange={(e) =>
                onEditLayer((l) => ({ ...l, action: e.target.value }), "action")
              }
            />
          </Field>
        </>
      )
    case "prop":
      return (
        <>
          <ReadOnly
            label="Prop"
            value={
              props.find((p) => p.id === layer.prop_id)?.name ?? layer.prop_id
            }
          />
          <Field label="Orientation" id="prop-orientation">
            <EnumSelect
              id="prop-orientation"
              value={layer.orientation}
              labels={ORIENTATION_LABELS}
              onChange={(orientation) =>
                onEditLayer((l) => ({ ...l, orientation }), "orientation")
              }
            />
          </Field>
        </>
      )
    case "text":
      return (
        <>
          <Field label="Text" id="text-text">
            <Textarea
              id="text-text"
              rows={3}
              value={layer.text}
              onChange={(e) =>
                onEditLayer((l) => ({ ...l, text: e.target.value }), "text")
              }
            />
          </Field>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Font" id="text-font">
              <EnumSelect
                id="text-font"
                value={layer.font}
                labels={FONT_LABELS}
                onChange={(font) =>
                  onEditLayer((l) => ({ ...l, font }), "font")
                }
              />
            </Field>
            <Field label="Alignment" id="text-align">
              <EnumSelect
                id="text-align"
                value={layer.align}
                labels={ALIGN_LABELS}
                onChange={(align) =>
                  onEditLayer((l) => ({ ...l, align }), "align")
                }
              />
            </Field>
            <NumberField
              id="text-size"
              label="Size"
              value={layer.size}
              min={1}
              onChange={(v) =>
                v > 0 && onEditLayer((l) => ({ ...l, size: v }), "size")
              }
            />
            <Field label="Colour" id="text-colour">
              <input
                id="text-colour"
                type="color"
                className="h-8 w-full cursor-pointer rounded-md border bg-transparent"
                value={layer.colour}
                onChange={(e) =>
                  onEditLayer(
                    (l) => ({ ...l, colour: e.target.value }),
                    "colour"
                  )
                }
              />
            </Field>
          </div>
        </>
      )
    case "image":
      return (
        <>
          <input
            ref={file}
            type="file"
            accept="image/png,image/jpeg"
            className="hidden"
            onChange={(e) => {
              const chosen = e.target.files?.[0]
              e.target.value = ""
              if (chosen) {
                onReplaceImage(chosen)
              }
            }}
          />
          <Button
            variant="outline"
            size="sm"
            hidden={readOnly}
            onClick={() => file.current?.click()}
          >
            <ImageUpIcon />
            Replace image
          </Button>
        </>
      )
    case "freehand":
      return (
        <p className="text-xs text-muted-foreground">
          {layer.strokes.length === 1
            ? "1 stroke."
            : `${layer.strokes.length} strokes.`}{" "}
          Draw into it with the brush (B), rub parts out with the eraser (E),
          and warp it with Distort (D).
        </p>
      )
    case "group":
      return null
  }
}

function Field({
  label,
  id,
  children,
}: {
  label: string
  id: string
  children: React.ReactNode
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}

function ReadOnly({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm">{value}</p>
    </div>
  )
}

/**
 * A generated layer's picture: whether it's up to date, out of date (and what changed), not drawn yet, being drawn or
 * waiting its turn (or why it couldn't be), and the button to draw it. Drawing it again is only on offer once something
 * it's drawn from has changed -- it would come out the same -- or while there are unsaved edits that might have.
 */
function GenerateControls({
  freshness,
  unsaved,
  progress,
  onGenerate,
  readOnly,
}: {
  freshness: Freshness
  unsaved: boolean
  progress?: LayerProgress
  onGenerate: () => void
  /** Saying where it stands, with no button */
  readOnly: boolean
}) {
  const busy = progress?.state === "drawing" || progress?.state === "waiting"
  const upToDate = freshness.state === "current" && !unsaved
  return (
    <div className="space-y-2">
      <p
        className={cn(
          "text-xs text-muted-foreground",
          !busy &&
            freshness.state === "stale" &&
            "text-amber-600 dark:text-amber-400"
        )}
      >
        {progress?.state === "drawing"
          ? "Drawing it now..."
          : progress?.state === "waiting"
            ? "Waiting its turn to be drawn."
            : freshness.state === "stale"
              ? `Out of date: ${changesText(freshness.changes)} changed since it was drawn.`
              : freshness.state === "current"
                ? "Up to date -- nothing it's drawn from has changed."
                : "Not drawn yet -- the canvas shows a placeholder (or its reference)."}
      </p>
      {progress?.state === "failed" && (
        <p className="text-xs text-destructive">
          Couldn&apos;t be drawn: {progress.error}
        </p>
      )}
      <Button
        variant="outline"
        size="sm"
        hidden={readOnly}
        disabled={busy || upToDate}
        title={
          upToDate
            ? "Nothing it's drawn from has changed, so it would come out the same"
            : undefined
        }
        onClick={onGenerate}
      >
        {busy ? (
          <LoaderCircleIcon className="animate-spin" />
        ) : (
          <SparklesIcon />
        )}
        {busy
          ? "Drawing..."
          : freshness.state === "undrawn"
            ? "Generate"
            : "Regenerate"}
      </Button>
    </div>
  )
}
