/**
 * Typed client for the TaleBoard API.
 *
 * Types come from src/api/schema.d.ts, generated from the backend's OpenAPI schema (npm run gen:api).
 *
 * Every request carries the signed-in user's Cognito access token -- the API's JWT authorizer refuses anything without one.
 */
import { fetchAuthSession } from "aws-amplify/auth"
import createClient from "openapi-fetch"

import type { paths } from "@/api/schema"

const apiUrl = import.meta.env.VITE_API_URL

/** Set when the build is missing its API settings, so the app can say so rather than fail every request */
export const configError = !apiUrl
  ? "This build is missing VITE_API_URL (see frontend/README.md)."
  : null

export const api = createClient<paths>({
  baseUrl: apiUrl?.replace(/\/+$/, ""),
})

api.use({
  async onRequest({ request }) {
    // Amplify swaps an expired access token for a fresh one first (using the refresh token), so this is always current
    const { tokens } = await fetchAuthSession()
    if (tokens?.accessToken) {
      request.headers.set(
        "Authorization",
        `Bearer ${tokens.accessToken.toString()}`
      )
    }
    return request
  },
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
export function unwrap<T>(result: {
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
 * Throws an ApiError unless the call succeeded -- for calls that answer with no body (204 No Content), which unwrap
 * would treat as missing data.
 */
export function ensureOk(result: {
  error?: unknown
  response: Response
}): void {
  if (!result.response.ok) {
    throw new ApiError(result.response.status, errorMessage(result))
  }
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
