import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

/**
 * A panel asking for one name -- for creating or renaming something.
 *
 * It closes itself only once onSubmit succeeds; if it throws, the error is shown and the typed name is kept.
 * Mount it fresh each time (the caller renders it only while open), so it always starts from initialName.
 */
export function NameDialog({
  title,
  description,
  label = "Name",
  initialName = "",
  maxLength,
  submitLabel,
  onSubmit,
  onClose,
}: {
  title: string
  description?: string
  label?: string
  initialName?: string
  maxLength: number
  submitLabel: string
  onSubmit: (name: string) => Promise<unknown>
  onClose: () => void
}) {
  const [name, setName] = useState(initialName)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await onSubmit(name.trim())
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
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            {description && (
              <DialogDescription>{description}</DialogDescription>
            )}
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="name-dialog-name">{label}</Label>
            <Input
              id="name-dialog-name"
              autoFocus
              required
              maxLength={maxLength}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? "Saving..." : submitLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
