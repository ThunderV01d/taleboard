import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { Shot } from "@/lib/api"
import { ANGLE_LABELS, SHOT_SIZE_LABELS } from "@/lib/labels"

/**
 * One shot: its image once rendered (a placeholder until then), number, description and framing.
 */
export function ShotCard({
  shot,
  number,
  onImageError,
  onClick,
}: {
  shot: Shot
  number: number
  onImageError: () => void
  onClick?: () => void
}) {
  return (
    <Card
      size="sm"
      className={
        onClick
          ? "cursor-pointer transition hover:ring-foreground/30"
          : undefined
      }
      onClick={onClick}
    >
      {shot.image_url ? (
        <img
          src={shot.image_url}
          alt={shot.description}
          loading="lazy"
          className="aspect-square w-full bg-muted object-cover"
          onError={onImageError}
        />
      ) : (
        <Skeleton className="aspect-square w-full rounded-none" />
      )}
      <CardContent className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
          <span className="whitespace-nowrap">Shot {number}</span>
          {!shot.rendered && (
            <span className="text-xs font-normal text-muted-foreground">
              rendering...
            </span>
          )}
          {shot.needs_review && (
            <Badge variant="destructive">Needs review</Badge>
          )}
        </div>
        <p className="line-clamp-2 text-muted-foreground">{shot.description}</p>
        <ShotMeta shot={shot} />
      </CardContent>
    </Card>
  )
}

/**
 * A shot's framing and duration, as small badges.
 */
export function ShotMeta({ shot }: { shot: Shot }) {
  return (
    <div className="flex flex-wrap gap-1">
      <Badge variant="secondary">{SHOT_SIZE_LABELS[shot.shot_size]}</Badge>
      <Badge variant="secondary">{ANGLE_LABELS[shot.angle]}</Badge>
      <Badge variant="outline">{shot.duration_s}s</Badge>
    </div>
  )
}
