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

/** Grid rows are drawn as distance from the camera (see the backend's layout.py), so they're named that way */
export const POSITION_LABELS: Record<Schemas["PositionCell"], string> = {
  top_left: "Back left",
  top_center: "Back centre",
  top_right: "Back right",
  mid_left: "Middle left",
  mid_center: "Middle centre",
  mid_right: "Middle right",
  bottom_left: "Front left",
  bottom_center: "Front centre",
  bottom_right: "Front right",
}

export const SIZE_LABELS: Record<Schemas["SizeInFrame"], string> = {
  small: "Small",
  medium: "Medium",
  large: "Large",
}

export const ORIENTATION_LABELS: Record<Schemas["Orientation"], string> = {
  towards_camera: "Facing camera",
  away_from_camera: "Facing away",
  left: "Facing left",
  right: "Facing right",
}

export const STATUS_LABELS: Record<Schemas["ProjectStatus"], string> = {
  created: "Not started",
  pending: "Queued",
  in_progress: "Rendering",
  complete: "Complete",
  failed: "Failed",
}