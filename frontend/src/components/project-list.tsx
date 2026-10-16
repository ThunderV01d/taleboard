import { useQuery } from "@tanstack/react-query"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { getProjects, type ProjectStatus } from "@/lib/api"
import { STATUS_LABELS } from "@/lib/labels"

const STATUS_VARIANTS: Record<
  ProjectStatus,
  "secondary" | "outline" | "destructive"
> = {
  created: "outline",
  pending: "outline",
  in_progress: "outline",
  complete: "secondary",
  failed: "destructive",
}

/**
 * Every storyboard made so far, newest first -- so a project is never lost along with its link.
 */
export function ProjectList({
  onOpen,
}: {
  onOpen: (projectId: string) => void
}) {
  const projects = useQuery({ queryKey: ["projects"], queryFn: getProjects })

  if (projects.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't load your storyboards</AlertTitle>
        <AlertDescription>{projects.error.message}</AlertDescription>
      </Alert>
    )
  }

  return (
    <section className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <h2 className="text-lg font-semibold">Your storyboards</h2>
      {projects.isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : projects.data.length === 0 ? (
        <p className="text-muted-foreground">
          Nothing yet -- storyboards you start appear here.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {projects.data.map((project) => (
            <li key={project.project_id}>
              <Card
                size="sm"
                className="cursor-pointer transition hover:ring-foreground/30"
                onClick={() => onOpen(project.project_id)}
              >
                <CardContent className="flex items-center justify-between gap-4">
                  <div className="flex min-w-0 flex-col">
                    <span className="truncate font-medium">{project.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(project.created_at).toLocaleDateString(
                        undefined,
                        { day: "numeric", month: "short", year: "numeric" }
                      )}
                      {project.shot_count !== null &&
                        ` · ${project.shot_count} shots`}
                    </span>
                  </div>
                  <Badge variant={STATUS_VARIANTS[project.status]}>
                    {STATUS_LABELS[project.status]}
                  </Badge>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
