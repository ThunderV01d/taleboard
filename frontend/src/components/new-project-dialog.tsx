import { FileTextIcon, SquareIcon } from "lucide-react"
import { useState, type FormEvent } from "react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
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
import { Textarea } from "@/components/ui/textarea"
import { MAX_STORY_LENGTH, useImportStory } from "@/lib/generation"
import { MAX_NAME_LENGTH, useCreateProject } from "@/lib/projects"

/** How a new project starts */
type Start = "blank" | "story"

/**
 * The panel for starting a project: a name, and either a blank project or one made from a story -- broken down into
 * its characters, props, places, scenes and shots (and, by default, drawn).
 *
 * The project is created first, then the story queued for import. If the import can't be queued, the project is kept
 * (and said so), so trying again only retries the import rather than making a second project.
 */
export function NewProjectDialog({
  onCreated,
  onClose,
}: {
  onCreated: (projectId: string) => void
  onClose: () => void
}) {
  const createProject = useCreateProject()
  const importStory = useImportStory()
  const [name, setName] = useState("")
  const [start, setStart] = useState<Start>("blank")
  const [story, setStory] = useState("")
  const [draw, setDraw] = useState(true)
  // The project made by an earlier attempt whose import couldn't be queued
  const [created, setCreated] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const ready = name.trim() !== "" && (start === "blank" || story.trim() !== "")

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const projectId =
        created ?? (await createProject.mutateAsync(name.trim())).project_id
      setCreated(projectId)
      if (start === "story") {
        await importStory.mutateAsync({ projectId, story, draw })
      }
      onCreated(projectId)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <form className="space-y-4" onSubmit={submit}>
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Start from nothing, or from a story you've written.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="new-project-name">Name</Label>
            <Input
              id="new-project-name"
              autoFocus
              required
              maxLength={MAX_NAME_LENGTH}
              disabled={created !== null}
              placeholder="A working title -- you can change it later"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div
            role="radiogroup"
            aria-label="How the project starts"
            className="grid grid-cols-2 gap-2"
          >
            <StartOption
              selected={start === "blank"}
              onSelect={() => setStart("blank")}
              icon={<SquareIcon />}
              title="Blank"
              detail="Add scenes, shots, characters and places yourself."
            />
            <StartOption
              selected={start === "story"}
              onSelect={() => setStart("story")}
              icon={<FileTextIcon />}
              title="From a story"
              detail="Paste a story -- it's broken down into scenes and shots for you."
            />
          </div>

          {start === "story" && (
            <div className="space-y-3">
              <div className="space-y-2">
                <div className="flex items-baseline justify-between">
                  <Label htmlFor="new-project-story">Story</Label>
                  <span className="text-xs text-muted-foreground">
                    {story.length.toLocaleString()} /{" "}
                    {MAX_STORY_LENGTH.toLocaleString()}
                  </span>
                </div>
                <Textarea
                  id="new-project-story"
                  rows={12}
                  maxLength={MAX_STORY_LENGTH}
                  className="max-h-[50vh]"
                  placeholder="Paste your story here, with a blank line between paragraphs."
                  value={story}
                  onChange={(e) => setStory(e.target.value)}
                />
              </div>
              <label className="flex items-start gap-2 text-sm">
                <Checkbox
                  className="mt-0.5"
                  checked={draw}
                  onCheckedChange={(on) => setDraw(on === true)}
                />
                <span>
                  Draw every layer once it's broken down
                  <span className="block text-xs text-muted-foreground">
                    Every background, character and prop is generated, shot by
                    shot. Untick to lay the storyboard out first and draw it
                    from the editor later.
                  </span>
                </span>
              </label>
            </div>
          )}

          {error && (
            <p className="text-sm text-destructive">
              {created
                ? `The project was created, but the story couldn't be sent: ${error}`
                : error}
            </p>
          )}
          <DialogFooter>
            {created ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  onCreated(created)
                  onClose()
                }}
              >
                Open it blank
              </Button>
            ) : (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={onClose}
              >
                Cancel
              </Button>
            )}
            <Button type="submit" disabled={busy || !ready}>
              {busy
                ? "Creating..."
                : start === "story"
                  ? created
                    ? "Try again"
                    : "Create from story"
                  : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * One of the ways a project can start, as a selectable card.
 */
function StartOption({
  selected,
  onSelect,
  icon,
  title,
  detail,
}: {
  selected: boolean
  onSelect: () => void
  icon: React.ReactNode
  title: string
  detail: string
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-left transition [&_svg]:size-4 ${
        selected
          ? "border-primary ring-1 ring-primary"
          : "hover:border-foreground/30"
      }`}
    >
      <span className="flex items-center gap-2 font-medium">
        {icon}
        {title}
      </span>
      <span className="text-xs text-muted-foreground">{detail}</span>
    </button>
  )
}
