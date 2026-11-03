import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { previewGeneration } from "@/lib/generation"

/**
 * "Generate everything": says how many layers across the project still need drawing, and at most how many images
 * that takes, before anything is drawn -- then asks for it on confirm.
 *
 * The image count is a ceiling: images other shots already paid for (a shared background, a pose used twice) aren't
 * drawn again, so it's often fewer. It closes itself only once the request is made; if that fails, the error shows.
 */
export function GenerateAllDialog({
  projectId,
  onGenerate,
  onClose,
}: {
  projectId: string
  onGenerate: () => Promise<unknown>
  onClose: () => void
}) {
  const plan = useQuery({
    queryKey: ["generate-preview", projectId],
    queryFn: () => previewGeneration(projectId, {}),
    gcTime: 0, // Always counted afresh -- it changes with every edit
  })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const layers = plan.data?.layers ?? 0

  const confirm = async () => {
    setError(null)
    setBusy(true)
    try {
      await onGenerate()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Generate everything?</DialogTitle>
          <DialogDescription>
            Draws every layer in the project that isn&apos;t drawn yet, or has
            changed since it was -- after any jobs already running.
          </DialogDescription>
        </DialogHeader>
        <p className="text-sm">
          {plan.isPending
            ? "Counting..."
            : plan.isError
              ? `Couldn't count them: ${plan.error.message}`
              : layers === 0
                ? "Everything is already drawn."
                : `Draws ${layers} ${layers === 1 ? "layer" : "layers"} -- up to ${plan.data.images} ${plan.data.images === 1 ? "image" : "images"} (fewer if some are already drawn).`}
        </p>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {layers === 0 && plan.isSuccess ? "Close" : "Cancel"}
          </Button>
          {layers > 0 && (
            <Button disabled={busy} onClick={() => void confirm()}>
              {busy ? "Asking..." : "Generate"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
