import { keepPreviousData, useQuery } from "@tanstack/react-query"

import {
  getCharacters,
  getLocations,
  type Character,
  type JobStatus,
  type Location,
} from "@/lib/api"

/** A project's cast and locations, plus lookups for the names shots refer to by ID */
export type Gallery = {
  characters: Character[]
  locations: Location[]
  isLoading: boolean
  error: Error | null
  characterName: (characterId: string) => string
  locationName: (locationId: string | null) => string | null
  /** Fetches fresh image URLs (they're presigned, and expire) */
  refetch: () => void
}

/**
 * Loads a project's cast and locations -- the one source for both the gallery view and the names in the shot panel.
 *
 * They only exist once the story has been broken down, and their images appear while the job renders, so this reloads as each shot finishes (the same way the shots do).
 */
export function useGallery(
  projectId: string,
  job: JobStatus | undefined
): Gallery {
  const enabled = job?.total_shots !== null && job?.total_shots !== undefined
  const characters = useQuery({
    queryKey: ["characters", projectId, job?.rendered_shots],
    queryFn: () => getCharacters(projectId),
    enabled,
    placeholderData: keepPreviousData,
  })
  const locations = useQuery({
    queryKey: ["locations", projectId, job?.rendered_shots],
    queryFn: () => getLocations(projectId),
    enabled,
    placeholderData: keepPreviousData,
  })

  const characterNames = new Map(
    (characters.data ?? []).map((c) => [c.character_id, c.name])
  )
  const locationNames = new Map(
    (locations.data ?? []).map((l) => [l.location_id, l.name])
  )

  return {
    characters: characters.data ?? [],
    locations: locations.data ?? [],
    isLoading: characters.isPending || locations.isPending,
    error: characters.error ?? locations.error,
    characterName: (characterId) =>
      characterNames.get(characterId) ?? characterId,
    locationName: (locationId) =>
      locationId === null
        ? null
        : (locationNames.get(locationId) ?? locationId),
    refetch: () => {
      void characters.refetch()
      void locations.refetch()
    },
  }
}