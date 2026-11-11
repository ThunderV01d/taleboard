import {
  LoaderCircleIcon,
  MapPinIcon,
  PackageIcon,
  SparklesIcon,
  UsersIcon,
} from "lucide-react"
import {
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { Link, useParams, useSearchParams } from "react-router"

import { DeleteDialog } from "@/components/delete-dialog"
import { GenerateAllDialog } from "@/components/editor/generate-all-dialog"
import { SceneDialog } from "@/components/editor/scene-dialog"
import { ScenePicker } from "@/components/editor/scene-picker"
import { ShotDeck } from "@/components/editor/shot-deck"
import { ShotDialog } from "@/components/editor/shot-dialog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import {
  busyShots,
  isActive,
  latestImport,
  layerProgress,
  useFollowJobs,
  useGenerate,
  useJobs,
  type GenerationJob,
} from "@/lib/generation"
import { loadImage } from "@/lib/images"
import { readLastShot, writeLastShot } from "@/lib/last-shot"
import { canEdit, useProject } from "@/lib/projects"
import { useCharacters, useLocations, useProps } from "@/lib/registries"
import {
  useDeleteScene,
  useReorderScenes,
  useScenes,
  type Scene,
} from "@/lib/scenes"
import {
  useDeleteShot,
  useReorderShots,
  useShots,
  type Shot,
} from "@/lib/shots"

// The canvas (and Konva with it) loads only when a shot is opened, keeping it out of every other page's download
const ShotEditor = lazy(() =>
  import("@/components/canvas/shot-editor").then((module) => ({
    default: module.ShotEditor,
  }))
)

/** Which panel is open over the editor, if any */
type Panel =
  | { kind: "newScene" }
  | { kind: "editScene"; scene: Scene }
  | { kind: "deleteScene"; scene: Scene }
  | { kind: "newShot" }
  | { kind: "deleteShot"; shot: Shot; number: number }
  | { kind: "generateAll" }
  | null

/**
 * The project editor, filling the window: the project and its scene picker across the top, the selected shot's
 * canvas editor in the middle (layers on the left, details on the right), and the scene's shot deck along the bottom.
 *
 * The selected scene and shot live in the address (?scene=...&shot=...), so a refresh or a shared link opens the same
 * place; with none named -- coming back from a registry, say -- it opens the scene and shot last open here. Panels
 * don't -- closing one, or reloading, just returns to the editor.
 *
 * A project shared with the user to view (the guest's examples, say) opens read-only: scenes and shots can be opened
 * and looked through, but nothing can be added, moved, edited, deleted or generated. The API refuses all of that
 * anyway -- this just doesn't offer it.
 */
export function ProjectEditorPage() {
  const { projectId = "" } = useParams()
  const [search, setSearch] = useSearchParams()
  const project = useProject(projectId)
  const scenes = useScenes(projectId)
  const locations = useLocations(projectId)
  const characters = useCharacters(projectId)
  const props = useProps(projectId)
  const [panel, setPanel] = useState<Panel>(null)
  const jobs = useJobs(projectId)
  const generate = useGenerate(projectId)
  const jobList = jobs.data ?? []
  useFollowJobs(projectId, jobList)
  const progress = layerProgress(jobList)
  const drawing = busyShots(jobList)
  const lastImport = latestImport(jobList)
  // Where the open shot's editor puts its undo/redo and save status (in the toolbar row, left of the scene picker)
  const [toolbarSlot, setToolbarSlot] = useState<HTMLDivElement | null>(null)
  const close = () => setPanel(null)

  // The selection is the scene and shot the address names -- or with none named, the ones last open here -- falling
  // back to the first scene and shot (if those have gone, too)
  const remembered = useMemo(() => readLastShot(projectId), [projectId])
  const named = search.has("scene")
  const wantedScene = named ? search.get("scene") : remembered?.scene
  const wantedShot = named ? search.get("shot") : (remembered?.shot ?? null)
  const sceneList = scenes.data ?? []
  const scene =
    sceneList.find((s) => s.id === wantedScene) ?? sceneList[0] ?? null
  const shots = useShots(projectId, scene?.id ?? null)
  const shotList = shots.data ?? []
  const shotIndex = Math.max(
    0,
    shotList.findIndex((s) => s.id === wantedShot)
  )
  const shot = shotList[shotIndex] ?? null

  // Remember where the editor is, once its shots have loaded (until then, the shot isn't known)
  const sceneId = scene?.id ?? null
  const shotId = shots.data ? (shot?.id ?? null) : undefined
  useEffect(() => {
    if (sceneId && shotId !== undefined) {
      writeLastShot(projectId, { scene: sceneId, shot: shotId })
    }
  }, [projectId, sceneId, shotId])

  // Load the pictures of the shots either side of this one, so stepping to the next or previous shot draws it at once
  const previousShot = shotList[shotIndex - 1]
  const nextShot = shotList[shotIndex + 1]
  useEffect(() => {
    for (const near of [previousShot, nextShot]) {
      Object.values(near?.image_urls ?? {}).forEach(loadImage)
    }
  }, [previousShot, nextShot])
  const reorderScenes = useReorderScenes(projectId)
  const reorderShots = useReorderShots(projectId, scene?.id ?? "")
  const reorderError = reorderScenes.error ?? reorderShots.error

  const select = (sceneId: string, shotId?: string) =>
    setSearch(shotId ? { scene: sceneId, shot: shotId } : { scene: sceneId }, {
      replace: true,
    })

  const readOnly = !canEdit(project.data)

  if (project.isPending || scenes.isPending) {
    return <Skeleton className="h-96 w-full" />
  }
  if (project.isError || scenes.isError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Couldn't open this project</AlertTitle>
        <AlertDescription>
          {(project.error ?? scenes.error)?.message}
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* On a narrow screen: the shot's toolbar on one row, the scene picker and the buttons on the next */}
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2 lg:grid lg:grid-cols-[1fr_auto_1fr] lg:gap-3">
        {/* The open shot's undo/redo and save status are drawn here by its editor (a portal), on the left */}
        <div
          ref={setToolbarSlot}
          className="flex w-full min-w-0 flex-wrap items-center gap-2 lg:w-auto"
        />
        <div className="min-w-0 flex-1 lg:flex-none">
          <ScenePicker
            scenes={sceneList}
            locations={locations.data ?? []}
            current={scene}
            onSelect={(s) => select(s.id)}
            onReorder={(ids) => {
              // Pin the current scene (and shot) in the address first -- otherwise a page showing "the first scene"
              // would jump to whichever scene is first after the move
              if (scene) {
                select(scene.id, shot?.id)
              }
              reorderScenes.mutate(ids)
            }}
            onNew={() => setPanel({ kind: "newScene" })}
            onEdit={(s) => setPanel({ kind: "editScene", scene: s })}
            onDelete={(s) => setPanel({ kind: "deleteScene", scene: s })}
            readOnly={readOnly}
          />
        </div>
        {/* The buttons' words show only on a wide screen -- on a narrower one, their icons (and tooltips) */}
        <div className="flex justify-end gap-2">
          {!readOnly && (
            <Button
              size="sm"
              title="Draw every layer in the project that isn't drawn yet, or has changed since"
              onClick={() => setPanel({ kind: "generateAll" })}
            >
              {drawing.size > 0 ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <SparklesIcon />
              )}
              <span className="hidden xl:inline">Generate everything</span>
            </Button>
          )}
          <Button variant="outline" size="sm" asChild>
            <Link to={`/projects/${projectId}/characters`} title="Characters">
              <UsersIcon />
              <span className="hidden xl:inline">Characters</span>
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={`/projects/${projectId}/locations`} title="Locations">
              <MapPinIcon />
              <span className="hidden xl:inline">Locations</span>
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link to={`/projects/${projectId}/props`} title="Props">
              <PackageIcon />
              <span className="hidden xl:inline">Props</span>
            </Link>
          </Button>
        </div>
      </header>

      {reorderError && (
        <Alert variant="destructive" className="m-2 w-auto">
          <AlertTitle>Couldn't reorder</AlertTitle>
          <AlertDescription>{reorderError.message}</AlertDescription>
        </Alert>
      )}

      {!scene ? (
        lastImport && isActive(lastImport) ? (
          <Importing job={lastImport} />
        ) : lastImport?.status === "failed" ? (
          <ImportFailed job={lastImport} />
        ) : (
          <EmptyState>
            {readOnly
              ? "This project has no scenes yet."
              : "Add a scene to start laying out shots."}
          </EmptyState>
        )
      ) : shots.isPending ? (
        <Skeleton className="m-4 flex-1" />
      ) : shot ? (
        <Suspense fallback={<Skeleton className="m-4 flex-1" />}>
          <ShotEditor
            // Keyed, so each shot gets its own draft, undo history and selection
            key={shot.id}
            projectId={projectId}
            scene={scene}
            shot={shot}
            characters={characters.data ?? []}
            props={props.data ?? []}
            locations={locations.data ?? []}
            toolbarSlot={toolbarSlot}
            progress={progress}
            drawing={drawing.has(shot.id)}
            onGenerate={(target) => generate.mutateAsync(target)}
            readOnly={readOnly}
          />
        </Suspense>
      ) : (
        <EmptyState>
          {readOnly
            ? "This scene has no shots yet."
            : "This scene has no shots yet -- add one from the deck below."}
        </EmptyState>
      )}

      {scene && shots.data && (
        <footer className="shrink-0 border-t px-3 pt-1">
          <ShotDeck
            shots={shotList}
            drawing={drawing}
            readOnly={readOnly}
            selectedId={shot?.id ?? null}
            onSelect={(s) => select(scene.id, s.id)}
            onNew={() => setPanel({ kind: "newShot" })}
            onReorder={(ids) => {
              // Pin the open shot in the address first, so the page stays on it after the move
              select(scene.id, shot?.id)
              reorderShots.mutate(ids)
            }}
            onDelete={(s) =>
              setPanel({
                kind: "deleteShot",
                shot: s,
                number: shotList.indexOf(s) + 1,
              })
            }
          />
        </footer>
      )}

      {(panel?.kind === "newScene" || panel?.kind === "editScene") && (
        <SceneDialog
          projectId={projectId}
          scene={panel.kind === "editScene" ? panel.scene : undefined}
          onSaved={(saved) => select(saved.id)}
          onClose={close}
        />
      )}
      {panel?.kind === "deleteScene" && (
        <DeleteSceneDialog
          projectId={projectId}
          scene={panel.scene}
          onClose={close}
        />
      )}
      {panel?.kind === "newShot" && scene && (
        <ShotDialog
          projectId={projectId}
          sceneId={scene.id}
          onCreated={(created) => select(scene.id, created.id)}
          onClose={close}
        />
      )}
      {panel?.kind === "generateAll" && (
        <GenerateAllDialog
          projectId={projectId}
          onGenerate={() => generate.mutateAsync({})}
          onClose={close}
        />
      )}
      {panel?.kind === "deleteShot" && scene && (
        <DeleteShotDialog
          projectId={projectId}
          sceneId={scene.id}
          shot={panel.shot}
          number={panel.number}
          onClose={close}
        />
      )}
    </div>
  )
}

/**
 * A dashed box with a hint, where the shot would be.
 */
/**
 * Shown in place of the editor while a story is being imported into the (still empty) project.
 */
function Importing({ job }: { job: GenerationJob }) {
  return (
    <EmptyState>
      <div className="flex max-w-md flex-col items-center gap-2">
        <LoaderCircleIcon className="size-6 animate-spin" />
        <p className="font-medium text-foreground">
          {job.status === "queued"
            ? "Your story is waiting to be read..."
            : "Reading your story..."}
        </p>
        <p className="text-sm">
          It's being broken down into characters, props, places, scenes and
          shots -- this takes a few minutes, and carries on if you leave this
          page.
          {job.draw &&
            " Then every layer is drawn, and each shot fills in as it's done."}
        </p>
      </div>
    </EmptyState>
  )
}

/**
 * Shown in place of the editor when the project's story import failed -- the project is still there, empty.
 */
function ImportFailed({ job }: { job: GenerationJob }) {
  return (
    <div className="m-4 flex flex-1 items-center justify-center">
      <Alert variant="destructive" className="max-w-lg">
        <AlertTitle>Couldn't import the story</AlertTitle>
        <AlertDescription>
          <p>{job.error ?? "Something went wrong breaking it down."}</p>
          <p>
            The project is still here, empty -- add scenes by hand, or start a
            new project to try the story again.
          </p>
        </AlertDescription>
      </Alert>
    </div>
  )
}

function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="m-4 flex flex-1 items-center justify-center rounded-lg border border-dashed p-6 text-center text-muted-foreground">
      {children}
    </div>
  )
}

function DeleteSceneDialog({
  projectId,
  scene,
  onClose,
}: {
  projectId: string
  scene: Scene
  onClose: () => void
}) {
  const deleteScene = useDeleteScene(projectId)
  return (
    <DeleteDialog
      thing="scene"
      name={scene.name || "Untitled scene"}
      consequence="and all its shots will be deleted."
      onConfirm={() => deleteScene.mutateAsync(scene.id)}
      onClose={onClose}
    />
  )
}

function DeleteShotDialog({
  projectId,
  sceneId,
  shot,
  number,
  onClose,
}: {
  projectId: string
  sceneId: string
  shot: Shot
  number: number
  onClose: () => void
}) {
  const deleteShot = useDeleteShot(projectId, sceneId)
  return (
    <DeleteDialog
      thing="shot"
      name={`Shot ${number}`}
      consequence="and its layers will be deleted."
      onConfirm={() => deleteShot.mutateAsync(shot.id)}
      onClose={onClose}
    />
  )
}
