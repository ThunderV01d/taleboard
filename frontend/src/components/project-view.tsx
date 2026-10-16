import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { useRef, useState } from "react"
import { GalleryView } from "@/components/gallery-view"

import { ShotGrid, Storyboard } from "@/components/storyboard"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  getProject,
  getShots,
  getStatus,
  isRunning,
  type JobStatus,
  type Shot,
} from "@/lib/api"
import { useGallery } from "@/lib/gallery"

const POLL_INTERVAL_MS = 4000

/**
 * A project's render job: live progress while it runs, then the finished storyboard -- with its cast and locations a click away.
 */
export function ProjectView({ projectId }: { projectId: string }) {
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
  })
  const status = useQuery({
    queryKey: ["status", projectId],
    queryFn: () => getStatus(projectId),
    refetchInterval: (query) =>
      isRunning(query.state.data?.status) ? POLL_INTERVAL_MS : false,
  })
  const shots = useQuery({
    // Keyed on the rendered count, so the shots (and fresh image URLs) reload exactly when another shot finishes
    queryKey: ["shots", projectId, status.data?.rendered_shots],
    queryFn: () => getShots(projectId),
    enabled: status.data !== undefined,
    placeholderData: keepPreviousData,
  })
  const gallery = useGallery(projectId, status.data)
  const [view, setView] = useState<"storyboard" | "gallery">("storyboard")

  // Image URLs are presigned and expire -- a broken image means a stale URL, so refetch once per URL for fresh ones
  const refreshedUrls = useRef(new Set<string>())
  const onImageError = (shot: Shot) => {
    if (shot.image_url && !refreshedUrls.current.has(shot.image_url)) {
      refreshedUrls.current.add(shot.image_url)
      void shots.refetch()
    }
  }

  if (status.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load this storyboard</AlertTitle>
        <AlertDescription>{status.error.message}</AlertDescription>
      </Alert>
    )
  }
  if (!status.data) {
    return <Skeleton className="h-40 w-full" />
  }

  const job = status.data
  const shotList = shots.data ?? []

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-3">
        {project.data ? (
          <h1 className="text-2xl font-semibold">{project.data.name}</h1>
        ) : (
          <Skeleton className="h-8 w-64" />
        )}
        <p className="text-muted-foreground">{describe(job)}</p>
        {isRunning(job.status) && (
          <Progress
            value={
              job.total_shots ? (job.rendered_shots / job.total_shots) * 100 : 0
            }
          />
        )}
      </div>
      {job.status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>Rendering failed</AlertTitle>
          <AlertDescription>{job.error ?? "Unknown error"}</AlertDescription>
        </Alert>
      )}
      {job.total_shots !== null && (
        <div className="flex gap-2">
          <Button
            size="sm"
            variant={view === "storyboard" ? "default" : "outline"}
            onClick={() => setView("storyboard")}
          >
            Storyboard
          </Button>
          <Button
            size="sm"
            variant={view === "gallery" ? "default" : "outline"}
            onClick={() => setView("gallery")}
          >
            Cast & locations
          </Button>
        </div>
      )}
      {view === "gallery" && job.total_shots !== null ? (
        <GalleryView gallery={gallery} />
      ) : job.status === "complete" ? (
        <Storyboard
          shots={shotList}
          gallery={gallery}
          onImageError={onImageError}
        />
      ) : (
        <ShotGrid shots={shotList} onImageError={onImageError} />
      )}
    </div>
  )
}

/**
 * One line saying where the job is.
 */
function describe(job: JobStatus): string {
  switch (job.status) {
    case "created":
      return "No story has been submitted for this project."
    case "pending":
      return "Queued. The renderer is starting up -- after a quiet spell this takes about a minute."
    case "in_progress":
      return job.total_shots === null
        ? "Breaking the story down into shots..."
        : `Rendering: ${job.rendered_shots} of ${job.total_shots} shots done.`
    case "complete": {
      const review = job.shots_needing_review
        ? ` ${job.shots_needing_review} need${job.shots_needing_review === 1 ? "s" : ""} review.`
        : ""
      return `${job.total_shots} shots.${review}`
    }
    case "failed":
      return `Stopped after ${job.rendered_shots} of ${job.total_shots ?? "?"} shots.`
  }
}
