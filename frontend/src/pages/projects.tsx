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
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Skeleton } from "@/components/ui/skeleton"
import {
  useCreateProject,
  useDeleteProject,
  useProjects,
  useRenameProject,
  type Project,
} from "@/lib/projects"

/** Must match the API's limit on project names (ProjectIn) */
const MAX_NAME_LENGTH = 200

/** Which panel is open over the list, if any */
type Panel =
  | { kind: "create" }
  | { kind: "rename"; project: Project }
  | { kind: "delete"; project: Project }
  | null

/**
 * The signed-in user's projects, newest first: open, create, rename or delete one.
 */
export function ProjectsPage() {
  const navigate = useNavigate()
  const projects = useProjects()
  const createProject = useCreateProject()
  const renameProject = useRenameProject()
  const deleteProject = useDeleteProject()
  const [panel, setPanel] = useState<Panel>(null)
  const close = () => setPanel(null)

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Your projects</h1>
        <Button onClick={() => setPanel({ kind: "create" })}>
          <PlusIcon />
          New project
        </Button>
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
      ) : projects.data.length === 0 ? (
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
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.map((project) => (
            <li key={project.project_id}>
              <ProjectCard
                project={project}
                onRename={() => setPanel({ kind: "rename", project })}
                onDelete={() => setPanel({ kind: "delete", project })}
              />
            </li>
          ))}
        </ul>
      )}

      {panel?.kind === "create" && (
        <NameDialog
          title="New project"
          description="Give it a working title -- you can change it later."
          maxLength={MAX_NAME_LENGTH}
          submitLabel="Create"
          onSubmit={async (name) => {
            const project = await createProject.mutateAsync(name)
            navigate(`/projects/${project.project_id}`)
          }}
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
 * One project in the list: its name and creation date open it, and its menu renames or deletes it.
 */
function ProjectCard({
  project,
  onRename,
  onDelete,
}: {
  project: Project
  onRename: () => void
  onDelete: () => void
}) {
  return (
    <Card size="sm" className="transition hover:ring-foreground/30">
      <CardContent className="flex items-start justify-between gap-2">
        <Link
          to={`/projects/${project.project_id}`}
          className="flex min-w-0 flex-1 flex-col gap-1"
        >
          <span className="truncate font-medium">{project.name}</span>
          <span className="text-xs text-muted-foreground">
            Created{" "}
            {new Date(project.created_at).toLocaleDateString(undefined, {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
        </Link>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Project actions">
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
      </CardContent>
    </Card>
  )
}
