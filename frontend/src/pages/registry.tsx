import { ArrowLeftIcon, PlusIcon } from "lucide-react"
import { useState } from "react"
import { Link, useParams } from "react-router"

import { EntryDeleteDialog } from "@/components/registry/entry-delete-dialog"
import { EntryEditor } from "@/components/registry/entry-editor"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { FACING_LABELS, ORIENTATION_LABELS } from "@/lib/labels"
import { useProject } from "@/lib/projects"
import {
  entryImages,
  isRegistryKind,
  REGISTRY_NAMES,
  useRegistry,
  type Character,
  type Entry,
  type RegistryKind,
} from "@/lib/registries"
import { NotFoundPage } from "@/pages/not-found"

/**
 * One of a project's registries -- its characters, locations or props.
 */
export function RegistryPage() {
  const { projectId = "", registry } = useParams()
  if (!isRegistryKind(registry)) {
    return <NotFoundPage />
  }
  // Keyed, so switching registry starts afresh (back on the grid)
  return <RegistryView key={registry} projectId={projectId} kind={registry} />
}

/** The grid of entries, or one entry opened in its place (a new one has no ID yet) */
type Mode = { kind: "grid" } | { kind: "entry"; entryId: string | null }

/**
 * A registry's entries as a grid. Opening one (or "New") switches the page to that entry -- a mode, not a new page,
 * as the spec has it. What an entry looks like is edited here; where it stands in a shot is edited in the editor.
 */
function RegistryView({
  projectId,
  kind,
}: {
  projectId: string
  kind: RegistryKind
}) {
  const project = useProject(projectId)
  const entries = useRegistry(projectId, kind)
  const [mode, setMode] = useState<Mode>({ kind: "grid" })
  const [deleting, setDeleting] = useState<Entry | null>(null)
  const names = REGISTRY_NAMES[kind]

  const open =
    mode.kind === "entry" && mode.entryId
      ? entries.data?.find((entry) => entry.id === mode.entryId)
      : undefined

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <Link
            to={`/projects/${projectId}`}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:underline"
          >
            <ArrowLeftIcon className="size-3.5" />
            {project.data?.name ?? "Project"}
          </Link>
          <h1 className="text-2xl font-semibold">
            {mode.kind === "entry"
              ? (open?.name ?? `New ${names.one}`)
              : names.many}
          </h1>
        </div>
        {mode.kind === "grid" && (
          <Button onClick={() => setMode({ kind: "entry", entryId: null })}>
            <PlusIcon />
            New {names.one}
          </Button>
        )}
      </div>

      {entries.isPending ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="aspect-[3/4]" />
          ))}
        </div>
      ) : entries.isError ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn't load the {names.many.toLowerCase()}</AlertTitle>
          <AlertDescription>{entries.error.message}</AlertDescription>
        </Alert>
      ) : mode.kind === "entry" ? (
        <EntryEditor
          // Keyed, so the form starts afresh for each entry (and once a new entry is created)
          key={open?.id ?? "new"}
          projectId={projectId}
          kind={kind}
          entry={open}
          onSaved={(saved) => setMode({ kind: "entry", entryId: saved.id })}
          onBack={() => setMode({ kind: "grid" })}
          onDelete={setDeleting}
        />
      ) : entries.data.length === 0 ? (
        <p className="rounded-xl border border-dashed py-16 text-center text-muted-foreground">
          No {names.many.toLowerCase()} yet.
        </p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {entries.data.map((entry) => (
            <li key={entry.id}>
              <EntryCard
                kind={kind}
                entry={entry}
                onOpen={() => setMode({ kind: "entry", entryId: entry.id })}
              />
            </li>
          ))}
        </ul>
      )}

      {deleting && (
        <EntryDeleteDialog
          projectId={projectId}
          kind={kind}
          entry={deleting}
          onDeleted={() => setMode({ kind: "grid" })}
          onClose={() => setDeleting(null)}
        />
      )}
    </section>
  )
}

/**
 * One entry in the grid: its first drawn image (or its initial), name and description.
 */
function EntryCard({
  kind,
  entry,
  onOpen,
}: {
  kind: RegistryKind
  entry: Entry
  onOpen: () => void
}) {
  const image = entryImages(kind, entry, {
    orientations: ORIENTATION_LABELS,
    facings: FACING_LABELS,
  }).find((i) => i.url)
  const aliases = kind === "characters" ? (entry as Character).aliases : []

  return (
    <Card
      size="sm"
      className="h-full cursor-pointer transition hover:ring-foreground/30"
      onClick={onOpen}
    >
      <CardContent className="space-y-2">
        {image?.url ? (
          <img
            src={image.url}
            alt={entry.name}
            className="aspect-square w-full rounded-md bg-muted object-contain"
          />
        ) : (
          <div className="flex aspect-square w-full items-center justify-center rounded-md bg-muted text-3xl font-semibold text-muted-foreground">
            {entry.name.charAt(0).toUpperCase()}
          </div>
        )}
        <button
          className="block w-full truncate text-left font-medium"
          onClick={onOpen}
        >
          {entry.name}
        </button>
        {aliases.length > 0 && (
          <p className="truncate text-xs text-muted-foreground">
            aka {aliases.join(", ")}
          </p>
        )}
        <p className="line-clamp-2 text-xs text-muted-foreground">
          {entry.description || "No description"}
        </p>
      </CardContent>
    </Card>
  )
}
