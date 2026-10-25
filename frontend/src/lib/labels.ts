import type { components } from "@/api/schema"

type Schemas = components["schemas"]

export const SHOT_SIZE_LABELS: Record<Schemas["ShotSize"], string> = {
  close_up: "Close-up",
  medium: "Medium",
  wide: "Wide",
}

export const ANGLE_LABELS: Record<Schemas["CameraAngle"], string> = {
  eye_level: "Eye level",
  low: "Low angle",
  high: "High angle",
}

export const ORIENTATION_LABELS: Record<Schemas["Orientation"], string> = {
  towards_camera: "Facing camera",
  away_from_camera: "Facing away",
  left: "Facing left",
  right: "Facing right",
}

/** Which way the camera looks across the location -- picks the location's plate for that direction */
export const FACING_LABELS: Record<Schemas["Facing"], string> = {
  north: "North",
  east: "East",
  south: "South",
  west: "West",
}

export const TIME_OF_DAY_LABELS: Record<Schemas["TimeOfDay"], string> = {
  dawn: "Dawn",
  day: "Day",
  dusk: "Dusk",
  night: "Night",
}

export const ATMOSPHERE_LABELS: Record<Schemas["Atmosphere"], string> = {
  clear: "Clear",
  overcast: "Overcast",
  rainy: "Rainy",
  foggy: "Foggy",
  stormy: "Stormy",
  snowy: "Snowy",
}

export const LAYER_TYPE_LABELS: Record<
  Schemas["ShotOut"]["layers"][number]["type"],
  string
> = {
  background: "Background",
  character: "Character",
  prop: "Prop",
  text: "Text",
  image: "Image",
  group: "Group",
}

export const FONT_LABELS: Record<Schemas["TextLayer-Output"]["font"], string> =
  {
    sans: "Sans serif",
    serif: "Serif",
    mono: "Monospace",
    handwritten: "Handwritten",
  }

/** The CSS font each of the text layer's generic fonts is drawn with */
export const FONT_FAMILIES: Record<
  Schemas["TextLayer-Output"]["font"],
  string
> = {
  sans: "Geist Variable, Arial, sans-serif",
  serif: "Georgia, 'Times New Roman', serif",
  mono: "ui-monospace, Consolas, monospace",
  handwritten: "'Segoe Print', 'Comic Sans MS', cursive",
}

export const ALIGN_LABELS: Record<
  Schemas["TextLayer-Output"]["align"],
  string
> = {
  left: "Left",
  center: "Centre",
  right: "Right",
}
