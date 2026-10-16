import type { ReactNode } from "react"

import type { Shot } from "@/lib/api"
import type { Gallery } from "@/lib/gallery"
import {
  ANGLE_LABELS,
  ORIENTATION_LABELS,
  POSITION_LABELS,
  SHOT_SIZE_LABELS,
  SIZE_LABELS,
} from "@/lib/labels"

/**
 * Everything the breakdown decided about one shot: framing, where it takes place, and each character's placement and action. Read-only.
 */
export function ShotDetails({
  shot,
  gallery,
}: {
  shot: Shot
  gallery: Gallery
}) {
  const locationName = gallery.locationName(shot.location_id)

  return (
    <dl className="flex flex-col gap-4 text-sm">
      <div className="grid grid-cols-3 gap-2">
        <Field label="Shot size">{SHOT_SIZE_LABELS[shot.shot_size]}</Field>
        <Field label="Angle">{ANGLE_LABELS[shot.angle]}</Field>
        <Field label="Duration">{shot.duration_s}s</Field>
      </div>
      <Field label="Location">
        {locationName ?? (
          <span className="text-muted-foreground">Not recorded</span>
        )}
        {shot.details && (
          <p className="text-muted-foreground">{shot.details}</p>
        )}
      </Field>
      <Field label={shot.regions.length === 1 ? "Character" : "Characters"}>
        {shot.regions.length === 0 ? (
          <span className="text-muted-foreground">Nobody in shot</span>
        ) : (
          <ul className="flex flex-col gap-3">
            {shot.regions.map((region) => (
              <li key={region.character_id} className="flex flex-col gap-0.5">
                <span className="font-medium">
                  {gallery.characterName(region.character_id)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {POSITION_LABELS[region.position]} ·{" "}
                  {SIZE_LABELS[region.size]} ·{" "}
                  {ORIENTATION_LABELS[region.orientation]}
                </span>
                <span>{region.action}</span>
              </li>
            ))}
          </ul>
        )}
      </Field>
    </dl>
  )
}

/**
 * One labelled value in the panel.
 */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <dd className="flex flex-col gap-1">{children}</dd>
    </div>
  )
}
