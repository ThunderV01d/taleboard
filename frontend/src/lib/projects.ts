/**
 * Projects: queries and changes, through TanStack Query.
 *
 * Every change invalidates the cached project list (only the list -- exact: true -- not every query under it), so any
 * page showing it refetches.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { components } from "@/api/schema"
import { api, ensureOk, unwrap } from "@/lib/api"

/** A project, with what the signed-in user may do with it (access): their own, or shared with them */
export type Project = components["schemas"]["ProjectOut"]

/**
 * Whether the signed-in user may change a project -- false for one shared with them to view (and the guest's), which
 * opens read-only, and while it's still loading.
 */
export function canEdit(project: Project | undefined): boolean {
  return project?.access === "owner" || project?.access === "editor"
}

/** Must match the API's limit on project names (ProjectIn) */
export const MAX_NAME_LENGTH = 200

/** Cache keys: the list, and one project by ID */
export const projectKeys = {
  all: ["projects"] as const,
  one: (projectId: string) => ["projects", projectId] as const,
}

/**
 * The signed-in user's projects, newest first.
 */
export function useProjects() {
  return useQuery({
    queryKey: projectKeys.all,
    queryFn: async () => unwrap(await api.GET("/projects")),
  })
}

/**
 * One project (a 404 if it doesn't exist or isn't yours).
 */
export function useProject(projectId: string) {
  return useQuery({
    queryKey: projectKeys.one(projectId),
    queryFn: async () =>
      unwrap(
        await api.GET("/projects/{project_id}", {
          params: { path: { project_id: projectId } },
        })
      ),
  })
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) =>
      unwrap(await api.POST("/projects", { body: { name } })),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: projectKeys.all, exact: true }),
  })
}

export function useRenameProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      projectId,
      name,
    }: {
      projectId: string
      name: string
    }) =>
      unwrap(
        await api.PATCH("/projects/{project_id}", {
          params: { path: { project_id: projectId } },
          body: { name },
        })
      ),
    onSuccess: (project) => {
      queryClient.setQueryData(projectKeys.one(project.project_id), project)
      return queryClient.invalidateQueries({
        queryKey: projectKeys.all,
        exact: true,
      })
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (projectId: string) =>
      ensureOk(
        await api.DELETE("/projects/{project_id}", {
          params: { path: { project_id: projectId } },
        })
      ),
    onSuccess: (_, projectId) => {
      // Everything cached under this project (its scenes, shots, registries) goes too
      queryClient.removeQueries({ queryKey: projectKeys.one(projectId) })
      return queryClient.invalidateQueries({
        queryKey: projectKeys.all,
        exact: true,
      })
    },
  })
}
