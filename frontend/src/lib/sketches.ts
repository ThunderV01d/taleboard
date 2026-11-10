/**
 * Sketches: the user's own drawings in place of an entry's images -- a character's or prop's reference for one
 * orientation, or a location's plate for one facing. Queries and changes.
 *
 * A sketch is a layer graph like a shot's, edited in the canvas editor on a frame the shape of the image it stands in
 * for. Using it flattens it (in the browser) into a PNG, uploads that, and makes it the slot's image; the sketch
 * itself is kept, so it can be opened and edited again.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { components } from "@/api/schema"
import { api, ApiError, unwrap } from "@/lib/api"
import type { Saved } from "@/lib/canvas-editor"
import type { Frame } from "@/lib/layers"
import { registryKey, type Entry, type RegistryKind } from "@/lib/registries"
import { scenesKey } from "@/lib/scenes"

type Schemas = components["schemas"]
export type Sketch = Schemas["SketchOut"]
/** Which of an entry's images a sketch is for: an orientation (characters and props) or a facing (locations) */
export type Slot = Schemas["Orientation"] | Schemas["Facing"]

/** Each registry's sketch frame -- the shape of the image a sketch stands in for (must match the API's SKETCH_FRAMES) */
export const SKETCH_FRAMES: Record<RegistryKind, Frame> = {
  characters: { width: 512, height: 1024 },
  props: { width: 1024, height: 1024 },
  locations: { width: 1024, height: 1024 },
}

/** The drawing pad's address for one of an entry's sketches */
export function sketchPath(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
) {
  return `/projects/${projectId}/${kind}/${entryId}/sketches/${slot}`
}

/** Cache key for one slot's sketch -- under its registry's, so deleting the project drops it */
export function sketchKey(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
) {
  return [...registryKey(projectId, kind), entryId, "sketches", slot] as const
}

// The three registries' sketch routes are the same apart from their path segment and their slot's type, so one typed
// path stands in for all three (registries.ts spells each registry out, as their entries' shapes differ)
const SKETCH = "/projects/{project_id}/characters/{entry_id}/sketches/{slot}"
const USE = "/projects/{project_id}/characters/{entry_id}/sketches/{slot}/use"

function route<P extends string>(path: P, kind: RegistryKind): P {
  return path.replace("/characters/", `/${kind}/`) as P
}

function params(projectId: string, entryId: string, slot: Slot) {
  return {
    path: {
      project_id: projectId,
      entry_id: entryId,
      slot: slot as Schemas["Orientation"],
    },
  }
}

/**
 * Loads a slot's sketch -- null if it hasn't been sketched.
 */
export async function fetchSketch(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
): Promise<Sketch | null> {
  try {
    return unwrap(
      await api.GET(route(SKETCH, kind), {
        params: params(projectId, entryId, slot),
      })
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null
    }
    throw error
  }
}

/**
 * A slot's sketch (null if there isn't one yet).
 */
export function useSketch(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
) {
  return useQuery({
    queryKey: sketchKey(projectId, kind, entryId, slot),
    queryFn: () => fetchSketch(projectId, kind, entryId, slot),
    // The editor holds the copy it's editing -- refetching underneath it would only report its own saves back
    staleTime: Infinity,
  })
}

/**
 * A sketch as the canvas editor holds it -- one that doesn't exist yet starts at version 0, with these layers.
 */
export function savedSketch(
  sketch: Sketch | null,
  start: Saved["draft"]["layers"] = []
): Saved<Record<string, never>> {
  return {
    version: sketch?.version ?? 0,
    draft: { fields: {}, layers: sketch?.layers ?? start },
  }
}

/**
 * Saves a slot's sketch (creating it at version 0). Refused (an ApiError with status 409) if it's been saved since.
 */
export function useSaveSketch(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (body: Schemas["SketchSave"]) =>
      unwrap(
        await api.PUT(route(SKETCH, kind), {
          params: params(projectId, entryId, slot),
          body,
        })
      ),
    onSuccess: (saved) =>
      queryClient.setQueryData(
        sketchKey(projectId, kind, entryId, slot),
        saved
      ),
  })
}

/** After a slot's image changes, its entry is refetched -- and the shots whose layers are drawn from it */
function refreshEntry(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: string,
  kind: RegistryKind
) {
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: registryKey(projectId, kind),
      exact: true,
    }),
    queryClient.invalidateQueries({ queryKey: scenesKey(projectId) }),
  ])
}

/**
 * Makes a flattened sketch (an uploaded PNG) the slot's image, cut out of its background unless asked not to.
 */
export function useSketchAsImage(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  slot: Slot
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      image,
      removeBackground,
    }: {
      image: string
      removeBackground: boolean
    }): Promise<Entry> =>
      unwrap(
        await api.PUT(route(USE, kind), {
          params: params(projectId, entryId, slot),
          body: { image, remove_background: removeBackground },
        })
      ),
    onSuccess: () => refreshEntry(queryClient, projectId, kind),
  })
}

/**
 * Goes back to a generated image for the slot (drawn when a shot next needs it). The sketch itself is kept.
 */
export function useStopUsingSketch(
  projectId: string,
  kind: RegistryKind,
  entryId: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (slot: Slot): Promise<Entry> =>
      unwrap(
        await api.DELETE(route(USE, kind), {
          params: params(projectId, entryId, slot),
        })
      ),
    onSuccess: () => refreshEntry(queryClient, projectId, kind),
  })
}
