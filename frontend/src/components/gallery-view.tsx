import { cn } from "cn"
import { useRef } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { Gallery } from "@/lib/gallery"

/**
 * The story's cast (with the reference image every pose of them is matched to) and its locations (with the master plate every background of them is drawn from).
 */
export function GalleryView({ gallery }: { gallery: Gallery }) {
  // Image URLs are presigned and expire -- a broken image means a stale URL, so refetch once per URL for fresh ones
  const refreshedUrls = useRef(new Set<string>())
  const onImageError = (url: string) => {
    if (!refreshedUrls.current.has(url)) {
      refreshedUrls.current.add(url)
      gallery.refetch()
    }
  }

  if (gallery.error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load the cast and locations</AlertTitle>
        <AlertDescription>{gallery.error.message}</AlertDescription>
      </Alert>
    )
  }
  if (gallery.isLoading) {
    return <Skeleton className="h-64 w-full" />
  }

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Cast</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {gallery.characters.map((character) => (
            <Card key={character.character_id} size="sm">
              <Picture
                url={character.appearance_reference_url}
                alt={character.name}
                className="aspect-[3/4] object-contain p-2"
                onError={onImageError}
              />
              <CardContent className="flex flex-col gap-1">
                <span className="font-medium">{character.name}</span>
                {character.aliases.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    Also: {character.aliases.join(", ")}
                  </span>
                )}
                <p className="text-muted-foreground">{character.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
      <section className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold">Locations</h2>
        {gallery.locations.length === 0 ? (
          <p className="text-muted-foreground">
            This storyboard was made before locations were tracked.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {gallery.locations.map((location) => (
              <Card key={location.location_id} size="sm">
                <Picture
                  url={location.master_plate_url}
                  alt={location.name}
                  className="aspect-square object-cover"
                  onError={onImageError}
                />
                <CardContent className="flex flex-col gap-1">
                  <span className="font-medium">{location.name}</span>
                  <p className="text-muted-foreground">
                    {location.description}
                  </p>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

/**
 * A gallery image, or a placeholder until it has been generated.
 */
function Picture({
  url,
  alt,
  className,
  onError,
}: {
  url: string | null
  alt: string
  className: string
  onError: (url: string) => void
}) {
  if (!url) {
    return <Skeleton className={cn("w-full rounded-none", className)} />
  }
  return (
    <img
      src={url}
      alt={alt}
      loading="lazy"
      className={cn("w-full bg-muted", className)}
      onError={() => onError(url)}
    />
  )
}
