import { ArrowLeftIcon } from "lucide-react"
import { lazy, Suspense, useEffect, useState } from "react"
import { Link, useLocation, useNavigate, useParams } from "react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { FACING_LABELS, ORIENTATION_LABELS } from "@/lib/labels"
import { newImageLayer, type Layer } from "@/lib/layers"
import {
  isRegistryKind,
  useRegistry,
  type Character,
  type Entry,
  type Location,
  type Prop,
  type RegistryKind,
} from "@/lib/registries"
import { canEdit, useProject } from "@/lib/projects"
import { SKETCH_FRAMES, useSketch, type Slot } from "@/lib/sketches"
import { NotFoundPage } from "@/pages/not-found"

// The canvas (and Konva with it) loads only when a sketch is opened, keeping it out of every other page's download
const SketchEditor = lazy(() =>
  import("@/components/canvas/sketch-editor").then((module) => ({
    default: module.SketchEditor,
  }))
)

/** The name of each slot a registry's sketches are kept by: orientations, or a location's facings */
function slotLabels(kind: RegistryKind): Record<string, string> {
  return kind === "locations" ? FACING_LABELS : ORIENTATION_LABELS
}

/**
 * The drawing pad for one of an entry's images (a character's or prop's orientation, or a location's facing), filling
 * the window like the project editor: undo/redo, the save status and "Use this sketch" across the top, the canvas
 * editor below.
 */
export function SketchPage() {
  const { projectId = "", registry, entryId = "", slot = "" } = useParams()
  if (!isRegistryKind(registry) || !(slot in slotLabels(registry))) {
    return <NotFoundPage />
  }
  return (
    <SketchView
      key={`${registry}/${entryId}/${slot}`}
      projectId={projectId}
      kind={registry}
      entryId={entryId}
      slot={slot as Slot}
    />
  )
}

function SketchView({
  projectId,
  kind,
  entryId,
  slot,
}: {
  projectId: string
  kind: RegistryKind
  entryId: string
  slot: Slot
}) {
  const navigate = useNavigate()
  const location = useLocation()
  const project = useProject(projectId)
  const entries = useRegistry(projectId, kind)
  const sketch = useSketch(projectId, kind, entryId, slot)
  const [toolbarSlot, setToolbarSlot] = useState<HTMLDivElement | null>(null)

  // A picture chosen with "Upload" on the entry comes along in the navigation -- taken once, so a reload doesn't add
  // it again
  const [upload] = useState<File | undefined>(() => {
    const state = location.state as { upload?: unknown } | null
    return state?.upload instanceof File ? state.upload : undefined
  })
  useEffect(() => {
    if (upload) {
      void navigate(location.pathname, { replace: true, state: null })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only ever on opening
  }, [])

  const entry = entries.data?.find((e) => e.id === entryId)
  const current = entry ? slotImage(kind, entry, slot) : null
  // A first sketch starts from the picture it replaces, to trace over or rub into -- sized to the frame, so its
  // natural size is needed first
  const tracing = sketch.data === null && current !== null
  const size = useNaturalSize(tracing ? current.url : null)
  const back = `/projects/${projectId}/${kind}?entry=${entryId}`

  if (
    project.isPending ||
    entries.isPending ||
    sketch.isPending ||
    (tracing && size === undefined)
  ) {
    return <Skeleton className="m-4 flex-1" />
  }
  if (entries.isError || sketch.isError) {
    return (
      <Alert variant="destructive" className="m-4 w-auto">
        <AlertTitle>Couldn't open this sketch</AlertTitle>
        <AlertDescription>
          {(entries.error ?? sketch.error)?.message}
        </AlertDescription>
      </Alert>
    )
  }
  if (!entry) {
    return <NotFoundPage />
  }

  const start: Layer[] = []
  if (tracing && size) {
    const frame = SKETCH_FRAMES[kind]
    const layer = newImageLayer(current.key, "Current picture", frame)
    const scale = Math.min(frame.width / size.width, frame.height / size.height)
    start.push({
      ...layer,
      transform: { ...layer.transform, scale_x: scale, scale_y: scale },
    })
  }

  return (
    <div className="flex h-full flex-col">
      {/* On a narrow screen: the editor's toolbar on one row, the title and the way back on the next */}
      <header className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2 lg:grid lg:grid-cols-[1fr_auto_1fr] lg:gap-3">
        {/* The editor's undo/redo, save status and "Use this sketch" are drawn here (a portal), on the left */}
        <div
          ref={setToolbarSlot}
          className="flex w-full min-w-0 flex-wrap items-center gap-3 lg:w-auto"
        />
        <div className="min-w-0 flex-1 text-left lg:flex-none lg:text-center">
          <h1 className="font-medium">
            {entry.name} -- {slotLabels(kind)[slot]}
          </h1>
          <p className="text-xs text-muted-foreground">Sketch</p>
        </div>
        <div className="flex justify-end">
          <Button variant="outline" size="sm" asChild>
            <Link to={back}>
              <ArrowLeftIcon />
              Back to {entry.name}
            </Link>
          </Button>
        </div>
      </header>
      <Suspense fallback={<Skeleton className="m-4 flex-1" />}>
        <SketchEditor
          projectId={projectId}
          kind={kind}
          entryId={entryId}
          slot={slot}
          sketch={sketch.data}
          start={start}
          imageUrls={{ ...entry.image_urls, ...sketch.data?.image_urls }}
          toolbarSlot={toolbarSlot}
          upload={upload}
          onUsed={() => void navigate(back)}
          readOnly={!canEdit(project.data)}
        />
      </Suspense>
    </div>
  )
}

/** The picture an entry has for a slot now -- its S3 key and download URL -- or null if it has none yet */
function slotImage(
  kind: RegistryKind,
  entry: Entry,
  slot: Slot
): { key: string; url: string } | null {
  const reference =
    kind === "locations"
      ? (entry as Location).plates[slot as keyof Location["plates"]]
      : (entry as Character | Prop).references[
          slot as keyof Character["references"]
        ]
  const url = reference ? entry.image_urls[reference.image] : undefined
  return reference && url ? { key: reference.image, url } : null
}

/**
 * An image's size in pixels, once it's loaded: undefined while it loads, null if it can't be (or there's no URL).
 */
function useNaturalSize(
  url: string | null
): { width: number; height: number } | null | undefined {
  const [size, setSize] = useState<
    { url: string; size: { width: number; height: number } | null } | undefined
  >()
  useEffect(() => {
    if (!url) {
      return
    }
    const image = new Image()
    image.crossOrigin = "anonymous" // As the canvas loads it, so the browser's cached copy can be drawn (and exported)
    image.onload = () =>
      setSize({
        url,
        size: { width: image.naturalWidth, height: image.naturalHeight },
      })
    image.onerror = () => setSize({ url, size: null })
    image.src = url
  }, [url])
  if (!url) {
    return null
  }
  return size?.url === url ? size.size : undefined
}
