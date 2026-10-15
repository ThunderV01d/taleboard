/**
 * Typed client for the TaleBoard API.
 *
 * Types come from src/api/schema.d.ts, generated from the deployed API's live OpenAPI schema (npm run gen:api).
 */
import createClient from "openapi-fetch"

import type { components, paths } from "@/api/schema"

export type Project = components["schemas"]["ProjectOut"]
export type JobStatus = components["schemas"]["StatusOut"]
export type ProjectStatus = components["schemas"]["ProjectStatus"]
export type Shot = components["schemas"]["ShotOut"]

const apiUrl = import.meta.env.VITE_API_URL
const apiKey = import.meta.env.VITE_API_KEY

/** Set when the build is missing its API settings, so the app can say so rather than fail every request */
export const configError =
  !apiUrl || !apiKey
    ? "This build is missing VITE_API_URL or VITE_API_KEY (see frontend/README.md)."
    : null

const api = createClient<paths>({
  baseUrl: apiUrl?.replace(/\/+$/, ""),
  headers: { "X-API-Key": apiKey },
})

/** A failed API call, carrying the API's own error message where it gave one */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/**
 * Returns a call's data, or throws an ApiError with a readable message.
 */
function unwrap<T>(result: {
  data?: T
  error?: unknown
  response: Response
}): T {
  if (result.response.ok && result.data !== undefined) {
    return result.data
  }
  throw new ApiError(result.response.status, errorMessage(result))
}

/**
 * Pulls a readable message out of a FastAPI error body ({"detail": "..."} or a list of validation errors).
 */
function errorMessage(result: { error?: unknown; response: Response }): string {
  const detail = (result.error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === "string") {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item: { msg?: string }) => item.msg ?? String(item))
      .join("; ")
  }
  return `Request failed (HTTP ${result.response.status})`
}

/** True while a job is queued or rendering, ie:- while its status is worth polling */
export function isRunning(status: ProjectStatus | undefined): boolean {
  return status === "pending" || status === "in_progress"
}

/**
 * Creates a project and submits its story, returning the new project's ID.
 */
export async function startStoryboard(
  name: string,
  story: string
): Promise<string> {
  const project = unwrap(await api.POST("/projects", { body: { name } }))
  unwrap(
    await api.POST("/projects/{project_id}/story", {
      params: { path: { project_id: project.project_id } },
      body: { story },
    })
  )
  return project.project_id
}

export async function getProject(projectId: string): Promise<Project> {
  return unwrap(
    await api.GET("/projects/{project_id}", {
      params: { path: { project_id: projectId } },
    })
  )
}

export async function getStatus(projectId: string): Promise<JobStatus> {
  return unwrap(
    await api.GET("/projects/{project_id}/status", {
      params: { path: { project_id: projectId } },
    })
  )
}

/** Every shot so far, rendered or not -- each rendered one with a fresh, short-lived image URL */
export async function getShots(projectId: string): Promise<Shot[]> {
  return unwrap(
    await api.GET("/projects/{project_id}/shots", {
      params: { path: { project_id: projectId } },
    })
  )
}
