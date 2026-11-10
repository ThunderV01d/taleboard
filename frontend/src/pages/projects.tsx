import {
  EllipsisIcon,
  FolderOpenIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react"
import { useState } from "react"
import { Link, useNavigate } from "react-router"

import { DeleteDialog } from "@/components/delete-dialog"
import { NameDialog } from "@/components/name-dialog"
import { NewProjectDialog } from "@/components/new-project-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import { useAuth } from "@/lib/auth-state"
import {
  MAX_NAME_LENGTH,
  useDeleteProject,
  useProjects,
  useRenameProject,
  type Project,
} from "@/lib/projects"

/** Which panel is open over the list, if any */
type Panel =
  | { kind: "create" }
  | { kind: "rename"; project: Project }
  | { kind: "delete"; project: Project }
  | null

/**
 * The signed-in user's projects, newest first: open, create, rename or delete one -- then the projects shared with
 * them to view, which only open. A guest only has the shared example projects.
 */
export function ProjectsPage() {
  const navigate = useNavigate()
  const guest = useAuth().status === "guest"
  const projects = useProjects()
  const own = projects.data?.filter((p) => p.access === "owner") ?? []
  const shared = projects.data?.filter((p) => p.access !== "owner") ?? []
  const renameProject = useRenameProject()
  const deleteProject = useDeleteProject()
  const [panel, setPanel] = useState<Panel>(null)
  const close = () => setPanel(null)

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {guest ? "Example projects" : "Your projects"}
        </h1>
        {!guest && (
          <Button onClick={() => setPanel({ kind: "create" })}>
            <PlusIcon />
            New project
          </Button>
        )}
      </div>

      {projects.isPending ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-20" />
          ))}
        </div>
      ) : projects.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load your projects</AlertTitle>
          <AlertDescription>{projects.error.message}</AlertDescription>
        </Alert>
      ) : guest ? (
        shared.length === 0 ? (
          <p className="rounded-xl border border-dashed py-16 text-center text-muted-foreground">
            There are no example projects to look at just yet.
          </p>
        ) : (
          <ProjectGrid projects={shared} />
        )
      ) : own.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed py-16 text-center">
          <FolderOpenIcon className="size-8 text-muted-foreground" />
          <p className="text-muted-foreground">
            No projects yet. Start one to build your first storyboard.
          </p>
          <Button
            variant="outline"
            onClick={() => setPanel({ kind: "create" })}
          >
            New project
          </Button>
        </div>
      ) : (
        <ProjectGrid
          projects={own}
          onRename={(project) => setPanel({ kind: "rename", project })}
          onDelete={(project) => setPanel({ kind: "delete", project })}
        />
      )}

      {!guest && shared.length > 0 && (
        <>
          <h2 className="pt-4 text-lg font-semibold">Shared with you</h2>
          <ProjectGrid projects={shared} />
        </>
      )}

      {panel?.kind === "create" && (
        <NewProjectDialog
          onCreated={(projectId) => navigate(`/projects/${projectId}`)}
          onClose={close}
        />
      )}
      {panel?.kind === "rename" && (
        <NameDialog
          title="Rename project"
          initialName={panel.project.name}
          maxLength={MAX_NAME_LENGTH}
          submitLabel="Rename"
          onSubmit={(name) =>
            renameProject.mutateAsync({
              projectId: panel.project.project_id,
              name,
            })
          }
          onClose={close}
        />
      )}
      {panel?.kind === "delete" && (
        <DeleteDialog
          thing="project"
          name={panel.project.name}
          consequence="and everything in it -- its scenes, shots, characters, locations, props and images -- will be deleted."
          onConfirm={() => deleteProject.mutateAsync(panel.project.project_id)}
          onClose={close}
        />
      )}
    </section>
  )
}

/**
 * Projects as a grid of cards -- with a menu to rename or delete each, for the user's own.
 */
function ProjectGrid({
  projects,
  onRename,
  onDelete,
}: {
  projects: Project[]
  onRename?: (project: Project) => void
  onDelete?: (project: Project) => void
}) {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {projects.map((project) => (
        <li key={project.project_id}>
          <ProjectCard
            project={project}
            onRename={onRename && (() => onRename(project))}
            onDelete={onDelete && (() => onDelete(project))}
          />
        </li>
      ))}
    </ul>
  )
}

/**
 * One project in the list: its name and creation date open it, and (for the user's own) its menu renames or deletes
 * it. One shared with them says it's view only.
 */
function ProjectCard({
  project,
  onRename,
  onDelete,
}: {
  project: Project
  onRename?: () => void
  onDelete?: () => void
}) {
  return (
    <Card size="sm" className="transition hover:ring-foreground/30">
      <CardContent className="flex items-start justify-between gap-2">
        <Link
          to={`/projects/${project.project_id}`}
          className="flex min-w-0 flex-1 flex-col gap-1"
        >
          <span className="flex items-center gap-2">
            <span className="truncate font-medium">{project.name}</span>
            {project.access === "viewer" && (
              <Badge variant="outline">View only</Badge>
            )}
          </span>
          <span className="text-xs text-muted-foreground">
            Created{" "}
            {new Date(project.created_at).toLocaleDateString(undefined, {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
        </Link>
        {onRename && onDelete && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Project actions"
              >
                <EllipsisIcon />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onRename}>
                <PencilIcon />
                Rename
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={onDelete}>
                <Trash2Icon />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </CardContent>
    </Card>
  )
}
