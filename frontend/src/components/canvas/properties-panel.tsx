import {
  FlipHorizontal2Icon,
  FlipVertical2Icon,
  ImageUpIcon,
  RotateCcwIcon,
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
import { placedAt, type Layer, type Transform } from "@/lib/layers"
import type { Character, Prop } from "@/lib/registries"
import type { ShotFields } from "@/lib/shot-editor"
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
 * Generated layers show what they were drawn from (location and facing; character or prop and orientation). Changing
 * those is what will make "Regenerate" light up in Milestone 5; drawing the images themselves is Milestone 4.
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
        />
      </Section>

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
          <NumberField
            id="t-sx"
            label="Width scale"
            value={layer.transform.scale_x}
            step={0.05}
            decimals={2}
            onChange={(v) => set("scale_x", v)}
          />
          <NumberField
            id="t-sy"
            label="Height scale"
            value={layer.transform.scale_y}
            step={0.05}
            decimals={2}
            onChange={(v) => set("scale_y", v)}
          />
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
          <div className="flex flex-wrap gap-2">
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
}: {
  layer: Layer
  characters: Character[]
  props: Prop[]
  locationName: string
  onEditLayer: LayerEdit
  onReplaceImage: (file: File) => void
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
          <DrawnStatus drawn={layer.image !== null} />
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
          <DrawnStatus drawn={layer.image !== null} />
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
          <DrawnStatus drawn={layer.image !== null} />
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
            onClick={() => file.current?.click()}
          >
            <ImageUpIcon />
            Replace image
          </Button>
        </>
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
 * Whether a generated layer has its picture yet.
 */
function DrawnStatus({ drawn }: { drawn: boolean }) {
  return (
    <p className="text-xs text-muted-foreground">
      {drawn
        ? "Drawn. Regenerating it arrives in a later update."
        : "Not drawn yet -- the canvas shows a placeholder (or its reference). Generation arrives in a later update."}
    </p>
  )
}
