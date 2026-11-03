/**
 * Generation: asking for layers to be drawn, and following the jobs that draw them -- and story imports, which are
 * jobs too.
 *
 * A request reaches as far as it names -- the whole project, a shot, or one layer -- and becomes a job: one task per
 * layer, worked through in order on the server, behind the project's earlier jobs. The worker saves each image into
 * its shot as it's drawn, so following a job is a matter of refetching the shots its finished tasks are in.
 *
 * An import has no tasks: it breaks a story down into the project's registries, scenes and shots in one go (queueing
 * a generation job behind itself, if asked to draw everything), so following one is refetching all of those once it
 * completes.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useEffect, useRef } from "react"

import type { components } from "@/api/schema"
import { api, unwrap } from "@/lib/api"
import { projectKeys } from "@/lib/projects"
import { registryKey } from "@/lib/registries"
import { scenesKey } from "@/lib/scenes"
import { shotsKey } from "@/lib/shots"

export type GenerationJob = components["schemas"]["GenerationJob"]
export type GenerateTarget = components["schemas"]["GenerateIn"]
export type GeneratePlan = components["schemas"]["GeneratePlan"]

/** How often running jobs are checked on */
const POLL_MS = 3000

/** Must match the API's limit on an imported story's length (MAX_STORY_LENGTH) */
export const MAX_STORY_LENGTH = 50_000

/** Where one layer stands with generation, if anywhere */
export type LayerProgress =
  | { state: "waiting" } // In a job, behind other layers (or other jobs)
  | { state: "drawing" } // Being drawn now
  | { state: "failed"; error: string } // Its last attempt failed

/** Cache key for a project's generation jobs */
export function jobsKey(projectId: string) {
  return [...projectKeys.one(projectId), "jobs"] as const
}

/** Whether a job is still to finish -- waiting its turn, or running */
export function isActive(job: GenerationJob): boolean {
  return job.status === "queued" || job.status === "running"
}

/**
 * The project's newest story import, if it has had one (jobs are newest first).
 */
export function latestImport(jobs: GenerationJob[]): GenerationJob | null {
  return jobs.find((job) => job.kind === "import") ?? null
}

/**
 * The project's generation jobs, newest first -- checked on every few seconds while any of them is still running.
 */
export function useJobs(projectId: string) {
  return useQuery({
    queryKey: jobsKey(projectId),
    queryFn: async () =>
      unwrap(
        await api.GET("/projects/{project_id}/jobs", {
          params: { path: { project_id: projectId } },
        })
      ),
    refetchInterval: (query) =>
      query.state.data?.some(isActive) ? POLL_MS : false,
  })
}

/**
 * Asks for what a target names to be drawn. The new job goes into the cached list at once, which starts the polling.
 */
export function useGenerate(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (target: GenerateTarget) =>
      unwrap(
        await api.POST("/projects/{project_id}/generate", {
          params: { path: { project_id: projectId } },
          body: target,
        })
      ),
    onSuccess: (job) =>
      queryClient.setQueryData<GenerationJob[]>(
        jobsKey(projectId),
        (jobs = []) => [job, ...jobs]
      ),
  })
}

/**
 * Queues a story to be imported into an (empty) project -- broken down into its registries, scenes and shots, and
 * then drawn if `draw` is set. The new job goes into the project's cached list at once, which starts the polling.
 */
export function useImportStory() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      projectId,
      story,
      draw,
    }: {
      projectId: string
      story: string
      draw: boolean
    }) =>
      unwrap(
        await api.POST("/projects/{project_id}/import", {
          params: { path: { project_id: projectId } },
          body: { story, draw },
        })
      ),
    onSuccess: (job, { projectId }) =>
      queryClient.setQueryData<GenerationJob[]>(
        jobsKey(projectId),
        (jobs = []) => [job, ...jobs]
      ),
  })
}

/**
 * How many layers a target would draw, and at most how many images that takes -- nothing is drawn.
 */
export async function previewGeneration(
  projectId: string,
  target: GenerateTarget
): Promise<GeneratePlan> {
  return unwrap(
    await api.POST("/projects/{project_id}/generate/preview", {
      params: { path: { project_id: projectId } },
      body: target,
    })
  )
}

/**
 * Where each layer stands, by layer ID: waiting or drawing in a running job, or failed in its latest job. Jobs are
 * newest first, so a layer's newest job decides.
 */
export function layerProgress(
  jobs: GenerationJob[]
): Record<string, LayerProgress> {
  const progress: Record<string, LayerProgress> = {}
  const decided = new Set<string>() // Layers a newer job has already said something about (even "drawn")
  for (const job of jobs) {
    // The first pending task of a running job is the one being drawn; the rest of its tasks (and queued jobs) wait
    const drawing =
      job.status === "running"
        ? job.tasks.findIndex((task) => task.status === "pending")
        : -1
    job.tasks.forEach((task, index) => {
      if (decided.has(task.layer_id)) {
        return
      }
      decided.add(task.layer_id)
      if (isActive(job) && task.status === "pending") {
        progress[task.layer_id] =
          index === drawing ? { state: "drawing" } : { state: "waiting" }
      } else if (task.status === "failed") {
        progress[task.layer_id] = {
          state: "failed",
          error: task.error ?? "It couldn't be drawn",
        }
      } else if (task.status === "pending") {
        // Still pending in a job that has stopped: the job itself failed
        progress[task.layer_id] = {
          state: "failed",
          error: job.error ?? "Its job couldn't finish",
        }
      }
      // Done or skipped: settled, so nothing to show
    })
  }
  return progress
}

/**
 * The IDs of the shots with a layer waiting or being drawn.
 */
export function busyShots(jobs: GenerationJob[]): Set<string> {
  return new Set(
    jobs
      .filter(isActive)
      .flatMap((job) =>
        job.tasks
          .filter((task) => task.status === "pending")
          .map((task) => task.shot_id)
      )
  )
}

/**
 * Keeps the editor up to date as jobs run: each time a task finishes, the shots of its scene are refetched (the
 * worker has saved its image into one), and so are the registries (it may have drawn a new plate or reference). When
 * an import completes, the scenes and registries are refetched (it has filled them).
 */
export function useFollowJobs(projectId: string, jobs: GenerationJob[]) {
  const queryClient = useQueryClient()
  const seen = useRef<Map<string, number> | null>(null)
  const importStatuses = useRef<Map<string, string> | null>(null)

  useEffect(() => {
    const before = importStatuses.current
    importStatuses.current = new Map(
      jobs
        .filter((job) => job.kind === "import")
        .map((job) => [job.id, job.status])
    )
    const imported =
      before !== null &&
      jobs.some(
        (job) =>
          job.kind === "import" &&
          job.status === "complete" &&
          before.get(job.id) !== "complete"
      )
    if (imported) {
      void queryClient.invalidateQueries({
        queryKey: scenesKey(projectId),
        exact: true,
      })
      for (const kind of ["characters", "props", "locations"] as const) {
        void queryClient.invalidateQueries({
          queryKey: registryKey(projectId, kind),
          exact: true,
        })
      }
    }
  }, [jobs, projectId, queryClient])

  useEffect(() => {
    const finished = new Map<string, number>()
    const scenes = new Set<string>()
    for (const job of jobs) {
      const done = job.tasks.filter((task) => task.status !== "pending")
      finished.set(job.id, done.length)
      const before =
        seen.current?.get(job.id) ?? (seen.current ? 0 : done.length)
      done.slice(before).forEach((task) => scenes.add(task.scene_id))
      // A task's position doesn't say when it finished -- but tasks finish in order, so the newly finished ones are
      // the ones past the count seen last time
    }
    seen.current = finished
    if (scenes.size === 0) {
      return
    }
    scenes.forEach(
      (sceneId) =>
        void queryClient.invalidateQueries({
          queryKey: shotsKey(projectId, sceneId),
          exact: true,
        })
    )
    for (const kind of ["characters", "props", "locations"] as const) {
      void queryClient.invalidateQueries({
        queryKey: registryKey(projectId, kind),
        exact: true,
      })
    }
  }, [jobs, projectId, queryClient])
}
