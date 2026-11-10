import { CheckIcon, LoaderCircleIcon } from "lucide-react"
import { useState } from "react"

import {
  CanvasEditor,
  type EditorActions,
  type Loaded,
  type Persist,
} from "@/components/canvas/canvas-editor"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import type { Saved } from "@/lib/canvas-editor"
import type { Layer } from "@/lib/layers"
import type { RegistryKind } from "@/lib/registries"
import {
  fetchSketch,
  savedSketch,
  SKETCH_FRAMES,
  useSaveSketch,
  useSketchAsImage,
  type Sketch,
  type Slot,
} from "@/lib/sketches"
import { uploadImage } from "@/lib/uploads"

type SketchFields = Record<string, never>

function loaded(sketch: Sketch): Loaded<SketchFields> {
  return { saved: savedSketch(sketch), imageUrls: sketch.image_urls }
}

/**
 * The drawing pad: the canvas editor on one of an entry's sketches, on a frame the shape of the image it stands in
 * for. Its layers are drawings, uploaded pictures, text and groups -- never generated ones.
 *
 * "Use this sketch" saves it, flattens it into a PNG (on white, hidden layers left out), uploads that and makes it the
 * slot's image -- for a character or prop, cut out of its background unless "Keep its background" is ticked.
 *
 * Mount it with a key per slot: everything in it (the draft, undo history, selection) belongs to one sketch.
 */
export function SketchEditor({
  projectId,
  kind,
  entryId,
  slot,
  sketch,
  start,
  imageUrls,
  toolbarSlot,
  upload,
  onUsed,
  readOnly = false,
}: {
  projectId: string
  kind: RegistryKind
  entryId: string
  slot: Slot
  /** The sketch as saved -- null if this slot hasn't been sketched */
  sketch: Sketch | null
  /** What a new sketch starts with (the picture it replaces, to trace over or rub into) */
  start: Layer[]
  /** A download URL for each image key in the sketch (or in `start`) */
  imageUrls: Record<string, string>
  toolbarSlot: HTMLElement | null
  /** A picture to add as a layer as soon as it opens (from "Upload" on the entry) */
  upload?: File
  /** Called once the sketch is the slot's image */
  onUsed: () => void
  /** Looking only -- the project is shared with the user to view */
  readOnly?: boolean
}) {
  const saveSketch = useSaveSketch(projectId, kind, entryId, slot)
  const asImage = useSketchAsImage(projectId, kind, entryId, slot)
  const [document] = useState<Saved<SketchFields>>(() =>
    savedSketch(sketch, start)
  )
  const [keepBackground, setKeepBackground] = useState(false)
  const [using, setUsing] = useState(false)
  // Plates are the whole picture -- there's no background to cut away
  const cutsOut = kind !== "locations"

  const persist: Persist<SketchFields> = {
    save: async (draft, version) =>
      loaded(await saveSketch.mutateAsync({ layers: draft.layers, version })),
    // Used to settle a conflict, which needs the sketch as it is now
    fetch: async () => {
      const latest = await fetchSketch(projectId, kind, entryId, slot)
      return latest
        ? loaded(latest)
        : { saved: savedSketch(null), imageUrls: {} }
    },
  }

  const use = async ({ save, flatten, setProblem }: EditorActions) => {
    setUsing(true)
    setProblem(null)
    try {
      if (!(await save())) {
        return // The editor shows why
      }
      const png = await flatten()
      const key = await uploadImage(
        projectId,
        new File([png], `${entryId}-${slot}.png`, { type: "image/png" })
      )
      await asImage.mutateAsync({
        image: key,
        removeBackground: cutsOut && !keepBackground,
      })
      onUsed()
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    } finally {
      setUsing(false)
    }
  }

  return (
    <CanvasEditor<SketchFields>
      projectId={projectId}
      noun="sketch"
      frame={SKETCH_FRAMES[kind]}
      document={document}
      imageUrls={imageUrls}
      persist={persist}
      toolbarSlot={toolbarSlot}
      readOnly={readOnly}
      toolbar={(actions) =>
        readOnly ? null : (
          <>
            {cutsOut && (
              <Label
                className="flex items-center gap-2 text-sm font-normal"
                title="Leave unticked to cut the drawing out of its paper (the white around it)"
              >
                <Checkbox
                  checked={keepBackground}
                  onCheckedChange={(checked) =>
                    setKeepBackground(checked === true)
                  }
                />
                Keep its background
              </Label>
            )}
            <Button
              size="sm"
              title="Make this sketch the picture -- hidden layers are left out"
              disabled={using}
              onClick={() => void use(actions)}
            >
              {using ? (
                <LoaderCircleIcon className="animate-spin" />
              ) : (
                <CheckIcon />
              )}
              {using ? "Using..." : "Use this sketch"}
            </Button>
          </>
        )
      }
      uploadsFillFrame
      startWith={upload}
    />
  )
}
