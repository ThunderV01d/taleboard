/**
 * A scene's shots: queries and changes.
 *
 * Saving a shot sends the version it was loaded at -- if someone (or another tab) has saved it since, the API answers
 * 409 and the save is refused rather than overwriting their changes (see useSaveShot).
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { components } from "@/api/schema"
import { api, ensureOk, unwrap } from "@/lib/api"
import type { Saved } from "@/lib/canvas-editor"
import { scenesKey } from "@/lib/scenes"

export type Shot = components["schemas"]["ShotOut"]
export type ShotIn = components["schemas"]["ShotIn"]
export type ShotSave = components["schemas"]["ShotSave"]
export type Layer = Shot["layers"][number]

/** The shot fields edited alongside the layers */
export type ShotFields = Pick<
  Shot,
  "description" | "duration_s" | "shot_size" | "angle" | "details"
>

/** Cache key for a scene's shots -- under the scene's, so deleting the scene drops them */
export function shotsKey(projectId: string, sceneId: string) {
  return [...scenesKey(projectId), sceneId, "shots"] as const
}

/**
 * The scene's shots, in order.
 */
export function useShots(projectId: string, sceneId: string | null) {
  return useQuery({
    queryKey: shotsKey(projectId, sceneId ?? ""),
    queryFn: async () =>
      unwrap(
        await api.GET("/projects/{project_id}/scenes/{scene_id}/shots", {
          params: { path: { project_id: projectId, scene_id: sceneId! } },
        })
      ),
    enabled: sceneId !== null,
  })
}

/** Writes one shot into the cached list (replacing it, or adding it at the end) */
function withShot(shots: Shot[] = [], saved: Shot): Shot[] {
  return shots.some((shot) => shot.id === saved.id)
    ? shots.map((shot) => (shot.id === saved.id ? saved : shot))
    : [...shots, saved]
}

/**
 * Creates a shot at the end of the scene -- holding just a background layer, not generated yet.
 */
export function useCreateShot(projectId: string, sceneId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (shot: ShotIn) =>
      unwrap(
        await api.POST("/projects/{project_id}/scenes/{scene_id}/shots", {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: shot,
        })
      ),
    onSuccess: (saved) =>
      queryClient.setQueryData<Shot[]>(shotsKey(projectId, sceneId), (shots) =>
        withShot(shots, saved)
      ),
  })
}

/**
 * Saves a shot's framing and layers. Refused (an ApiError with status 409) if it's been saved since `version`.
 */
export function useSaveShot(projectId: string, sceneId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ shotId, shot }: { shotId: string; shot: ShotSave }) =>
      unwrap(
        await api.PUT(
          "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}",
          {
            params: {
              path: {
                project_id: projectId,
                scene_id: sceneId,
                shot_id: shotId,
              },
            },
            body: shot,
          }
        )
      ),
    onSuccess: (saved) =>
      queryClient.setQueryData<Shot[]>(shotsKey(projectId, sceneId), (shots) =>
        withShot(shots, saved)
      ),
  })
}

export function useDeleteShot(projectId: string, sceneId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (shotId: string) =>
      ensureOk(
        await api.DELETE(
          "/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}",
          {
            params: {
              path: {
                project_id: projectId,
                scene_id: sceneId,
                shot_id: shotId,
              },
            },
          }
        )
      ),
    onSuccess: (_, shotId) =>
      queryClient.setQueryData<Shot[]>(
        shotsKey(projectId, sceneId),
        (shots = []) => shots.filter((shot) => shot.id !== shotId)
      ),
  })
}

/**
 * Puts the scene's shots in a new order, given as the full list of their IDs. Shots that move are saved, so their
 * versions go up -- the answer carries the new ones.
 */
export function useReorderShots(projectId: string, sceneId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (shotIds: string[]) =>
      unwrap(
        await api.PUT("/projects/{project_id}/scenes/{scene_id}/shots/order", {
          params: { path: { project_id: projectId, scene_id: sceneId } },
          body: { shot_ids: shotIds },
        })
      ),
    // Shown in the new order straight away; a failure refetches the real order
    onMutate: (shotIds) =>
      queryClient.setQueryData<Shot[]>(
        shotsKey(projectId, sceneId),
        (shots = []) =>
          shotIds
            .map((id) => shots.find((shot) => shot.id === id))
            .filter((shot): shot is Shot => shot !== undefined)
      ),
    onError: () =>
      queryClient.invalidateQueries({
        queryKey: shotsKey(projectId, sceneId),
        exact: true,
      }),
    onSuccess: (shots) =>
      queryClient.setQueryData(shotsKey(projectId, sceneId), shots),
  })
}

/**
 * The editable part of a shot, ready to send back with a save.
 */
export function toSave(shot: Shot): ShotSave {
  return {
    description: shot.description,
    duration_s: shot.duration_s,
    shot_size: shot.shot_size,
    angle: shot.angle,
    details: shot.details,
    layers: shot.layers,
    version: shot.version,
  }
}

/**
 * A shot as the canvas editor holds it: its framing and layers, at its version.
 */
export function savedShot(shot: Shot): Saved<ShotFields> {
  const { description, duration_s, shot_size, angle, details, layers } = shot
  return {
    version: shot.version,
    draft: {
      fields: { description, duration_s, shot_size, angle, details },
      layers,
    },
  }
}

/**
 * Loads one shot fresh from the API (bypassing the cache) -- to see its latest version after a save conflict.
 */
export async function fetchShot(
  projectId: string,
  sceneId: string,
  shotId: string
): Promise<Shot> {
  return unwrap(
    await api.GET("/projects/{project_id}/scenes/{scene_id}/shots/{shot_id}", {
      params: {
        path: { project_id: projectId, scene_id: sceneId, shot_id: shotId },
      },
    })
  )
}
