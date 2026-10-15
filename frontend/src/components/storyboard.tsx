import { useState } from "react"

import { ShotCard, ShotMeta } from "@/components/shot-card"
import { Badge } from "@/components/ui/badge"
import {
  Carousel,
  CarouselContent,
  CarouselItem,
  CarouselNext,
  CarouselPrevious,
  type CarouselApi,
} from "@/components/ui/carousel"
import type { Shot } from "@/lib/api"

/**
 * The finished storyboard: a slideshow of every shot, with a clickable grid below it.
 */
export function Storyboard({
  shots,
  onImageError,
}: {
  shots: Shot[]
  onImageError: (shot: Shot) => void
}) {
  const [carousel, setCarousel] = useState<CarouselApi>()

  return (
    <div className="flex flex-col gap-10">
      <Carousel setApi={setCarousel} className="mx-auto w-full max-w-2xl">
        <CarouselContent>
          {shots.map((shot, index) => (
            <CarouselItem key={shot.shot_id}>
              <figure className="flex flex-col gap-3">
                {shot.image_url && (
                  <img
                    src={shot.image_url}
                    alt={shot.description}
                    className="aspect-square w-full rounded-xl bg-muted object-cover ring-1 ring-foreground/10"
                    onError={() => onImageError(shot)}
                  />
                )}
                <figcaption className="flex flex-col gap-2">
                  <div className="flex items-center gap-2 font-medium">
                    Shot {index + 1} of {shots.length}
                    {shot.needs_review && (
                      <Badge variant="destructive">Needs review</Badge>
                    )}
                  </div>
                  <p className="text-muted-foreground">{shot.description}</p>
                  <ShotMeta shot={shot} />
                </figcaption>
              </figure>
            </CarouselItem>
          ))}
        </CarouselContent>
        <CarouselPrevious className="max-sm:hidden" />
        <CarouselNext className="max-sm:hidden" />
      </Carousel>
      <ShotGrid
        shots={shots}
        onImageError={onImageError}
        onSelect={(index) => {
          carousel?.scrollTo(index)
          window.scrollTo({ top: 0, behavior: "smooth" })
        }}
      />
    </div>
  )
}

/**
 * Every shot as a card -- placeholders for the ones still rendering.
 */
export function ShotGrid({
  shots,
  onImageError,
  onSelect,
}: {
  shots: Shot[]
  onImageError: (shot: Shot) => void
  onSelect?: (index: number) => void
}) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {shots.map((shot, index) => (
        <ShotCard
          key={shot.shot_id}
          shot={shot}
          number={index + 1}
          onImageError={() => onImageError(shot)}
          onClick={onSelect && (() => onSelect(index))}
        />
      ))}
    </div>
  )
}
