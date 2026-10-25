/**
 * A project's scenes: queries and changes.
 *
 * Every change writes the API's answer straight into the cached list, so the scene list updates without a refetch.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { components } from "@/api/schema"
import { api, ensureOk, unwrap } from "@/lib/api"
import { projectKeys } from "@/lib/projects"

export type Scene = components["schemas"]["Scene"]
export type SceneIn = components["schemas"]["SceneIn"]

/** Cache key for a project's scenes -- under the project's, so deleting the project drops it */
export function scenesKey(projectId: string) {
  return [...projectKeys.one(projectId), "scenes"] as const
}

/**
 * The project's scenes, in story order.
 */
export function useScenes(projectId: string) {
  return useQuery({
    queryKey: scenesKey(projectId),
    queryFn: async () =>
      unwrap(
        await api.GET("/projects/{project_id}/scenes", {
          params: { path: { project_id: projectId } },
        })
      ),
  })
}

/**
 * Creates a scene (added at the end), or edits one when given its ID.
 */
export function useSaveScene(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      sceneId,
      scene,
    }: {
      sceneId?: string
      scene: SceneIn
    }) =>
      sceneId
        ? unwrap(
            await api.PATCH("/projects/{project_id}/scenes/{scene_id}", {
              params: { path: { project_id: projectId, scene_id: sceneId } },
              body: scene,
            })
          )
        : unwrap(
            await api.POST("/projects/{project_id}/scenes", {
              params: { path: { project_id: projectId } },
              body: scene,
            })
          ),
    onSuccess: (saved) =>
      queryClient.setQueryData<Scene[]>(scenesKey(projectId), (scenes = []) =>
        scenes.some((scene) => scene.id === saved.id)
          ? scenes.map((scene) => (scene.id === saved.id ? saved : scene))
          : [...scenes, saved]
      ),
  })
}

/**
 * Deletes a scene, and its shots with it.
 */
export function useDeleteScene(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (sceneId: string) =>
      ensureOk(
        await api.DELETE("/projects/{project_id}/scenes/{scene_id}", {
          params: { path: { project_id: projectId, scene_id: sceneId } },
        })
      ),
    onSuccess: (_, sceneId) => {
      queryClient.removeQueries({
        queryKey: [...scenesKey(projectId), sceneId],
      })
      queryClient.setQueryData<Scene[]>(scenesKey(projectId), (scenes = []) =>
        scenes.filter((scene) => scene.id !== sceneId)
      )
    },
  })
}

/**
 * Puts the scenes in a new order, given as the full list of their IDs.
 */
export function useReorderScenes(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (sceneIds: string[]) =>
      unwrap(
        await api.PUT("/projects/{project_id}/scenes/order", {
          params: { path: { project_id: projectId } },
          body: { scene_ids: sceneIds },
        })
      ),
    // Shown in the new order straight away (a drag shouldn't snap back while the request is in flight); a failure
    // refetches the real order
    onMutate: (sceneIds) =>
      queryClient.setQueryData<Scene[]>(scenesKey(projectId), (scenes = []) =>
        sceneIds
          .map((id) => scenes.find((scene) => scene.id === id))
          .filter((scene): scene is Scene => scene !== undefined)
      ),
    onError: () =>
      queryClient.invalidateQueries({
        queryKey: scenesKey(projectId),
        exact: true,
      }),
    onSuccess: (scenes) =>
      queryClient.setQueryData(scenesKey(projectId), scenes),
  })
}

/**
 * The IDs in a new order, with one moved a step earlier (-1) or later (+1). (Kept for keyboard reordering.)
 */
export function moved(ids: string[], id: string, step: -1 | 1): string[] {
  const from = ids.indexOf(id)
  const to = from + step
  if (from < 0 || to < 0 || to >= ids.length) {
    return ids
  }
  const next = [...ids]
  ;[next[from], next[to]] = [next[to], next[from]]
  return next
}
