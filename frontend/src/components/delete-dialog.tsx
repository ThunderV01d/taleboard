import { useState, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

/**
 * The one delete confirmation for everything -- projects, scenes, shots, characters, locations and props.
 *
 * `children` is for what else the delete takes with it (eg:- the shots a character appears in), shown under the
 * warning. It closes itself only once onConfirm succeeds; if it throws, the error is shown and nothing closes.
 */
export function DeleteDialog({
  thing,
  name,
  consequence,
  children,
  confirmLabel = "Delete",
  confirmDisabled = false,
  undoable = false,
  onConfirm,
  onClose,
}: {
  /** What's being deleted, in lower case -- "project", "scene"... */
  thing: string
  name: string
  /** What else goes with it, in a sentence */
  consequence?: string
  children?: ReactNode
  confirmLabel?: string
  confirmDisabled?: boolean
  /** True when the delete can be undone (layers, with Ctrl+Z) -- the warning says so instead of "can't be undone" */
  undoable?: boolean
  onConfirm: () => Promise<unknown>
  onClose: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    setError(null)
    setBusy(true)
    try {
      await onConfirm()
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
          <DialogTitle>
            {/^\d/.test(thing) ? `Delete ${thing}?` : `Delete this ${thing}?`}
          </DialogTitle>
          <DialogDescription>
            <span className="font-medium text-foreground">{name}</span>{" "}
            {consequence ? `${consequence} ` : ""}
            {undoable ? "Ctrl+Z brings it back." : "This can't be undone."}
          </DialogDescription>
        </DialogHeader>
        {children}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={busy || confirmDisabled}
            onClick={confirm}
          >
            {busy ? "Deleting..." : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
