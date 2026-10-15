import type { components } from "@/api/schema"

export const SHOT_SIZE_LABELS: Record<
  components["schemas"]["ShotSize"],
  string
> = {
  close_up: "Close-up",
  medium: "Medium",
  wide: "Wide",
}

export const ANGLE_LABELS: Record<
  components["schemas"]["CameraAngle"],
  string
> = {
  eye_level: "Eye level",
  low: "Low angle",
  high: "High angle",
}
