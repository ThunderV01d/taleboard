import { describe, expect, it, vi } from "vitest"

// The API client signs requests with Amplify, which doesn't load outside a browser -- and none is made here
vi.mock("@/lib/api", () => ({ api: {}, unwrap: vi.fn(), ensureOk: vi.fn() }))

import {
  busyShots,
  isActive,
  latestImport,
  layerProgress,
  type GenerationJob,
} from "@/lib/generation"

function job(changes: Partial<GenerationJob>): GenerationJob {
  return {
    id: "job",
    created_at: "2026-10-30T12:00:00Z",
    kind: "generate",
    draw: false,
    status: "queued",
    tasks: [],
    error: null,
    ...changes,
  }
}

describe("latestImport", () => {
  it("finds the newest import among a project's jobs (newest first)", () => {
    const jobs = [
      job({ id: "draw" }),
      job({ id: "second", kind: "import", status: "complete" }),
      job({ id: "first", kind: "import", status: "failed" }),
    ]

    expect(latestImport(jobs)?.id).toBe("second")
  })

  it("is null for a project that has never imported a story", () => {
    expect(latestImport([job({})])).toBeNull()
  })
})

describe("an import job", () => {
  it("is active while queued or running, like any job", () => {
    expect(isActive(job({ kind: "import", status: "queued" }))).toBe(true)
    expect(isActive(job({ kind: "import", status: "running" }))).toBe(true)
    expect(isActive(job({ kind: "import", status: "complete" }))).toBe(false)
  })

  it("has no tasks, so it never marks a layer or shot as drawing", () => {
    const jobs = [job({ kind: "import", status: "running", draw: true })]

    expect(layerProgress(jobs)).toEqual({})
    expect(busyShots(jobs).size).toBe(0)
  })
})
