import { ImageOffIcon, Trash2Icon } from "lucide-react"
import { useState, type FormEvent } from "react"

import { EnumSelect } from "@/components/enum-select"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { FACING_LABELS, ORIENTATION_LABELS, SETTING_LABELS } from "@/lib/labels"
import {
  entryImages,
  REGISTRY_NAMES,
  useSaveEntry,
  type Character,
  type Entry,
  type Location,
  type RegistryKind,
  type Views,
} from "@/lib/registries"

/** Must match the API's limits (EntryIn, View) */
const MAX_NAME = 100
const MAX_DESCRIPTION = 300
const MAX_VIEW = 200

const FACINGS = Object.keys(FACING_LABELS) as (keyof typeof FACING_LABELS)[]

/**
 * One registry entry, opened in place of the grid: its reference images (or a location's plates), and its name,
 * description and -- for characters -- aliases. With no entry, it's the form for a new one.
 *
 * A location also has a setting (indoors or out) and a line for what's on each side of it: each facing's view is drawn
 * from its own line plus the description, so the four views show different sides of the same place. A side with no
 * line shows the north view.
 *
 * Drawing the images (sketching, or generating) comes later: sketches in Milestone 5, generation in Milestone 4.
 */
export function EntryEditor({
  projectId,
  kind,
  entry,
  onSaved,
  onBack,
  onDelete,
}: {
  projectId: string
  kind: RegistryKind
  entry?: Entry
  onSaved: (entry: Entry) => void
  onBack: () => void
  onDelete: (entry: Entry) => void
}) {
  const saveEntry = useSaveEntry(projectId, kind)
  const [name, setName] = useState(entry?.name ?? "")
  const [description, setDescription] = useState(entry?.description ?? "")
  const [aliases, setAliases] = useState(
    kind === "characters"
      ? ((entry as Character | undefined)?.aliases ?? []).join(", ")
      : ""
  )
  const location =
    kind === "locations" ? (entry as Location | undefined) : undefined
  const [setting, setSetting] = useState(location?.setting ?? "interior")
  const [views, setViews] = useState<Views>(location?.views ?? {})
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const one = REGISTRY_NAMES[kind].one

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSaved(false)
    try {
      const result = await saveEntry.mutateAsync({
        entryId: entry?.id,
        fields: {
          name: name.trim(),
          description: description.trim(),
          ...(kind === "characters" && {
            aliases: aliases
              .split(",")
              .map((alias) => alias.trim())
              .filter(Boolean),
          }),
          ...(kind === "locations" && {
            setting,
            // Every side, so an emptied one is removed -- the API replaces a location's views whole
            views: Object.fromEntries(
              FACINGS.map((facing) => [
                facing,
                views[facing]?.trim() ?? "",
              ]).filter(([, view]) => view)
            ),
          }),
        },
      })
      setSaved(true)
      onSaved(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const images = entry
    ? entryImages(kind, entry, {
        orientations: ORIENTATION_LABELS,
        facings: FACING_LABELS,
      })
    : []

  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_22rem]">
      <section className="space-y-3">
        <h2 className="text-sm font-medium">
          {kind === "locations" ? "Views" : "References"}
        </h2>
        {entry ? (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {images.map((image) => (
              <li key={image.label} className="space-y-1">
                {kind === "locations" &&
                image.facing !== "north" &&
                !views[image.facing as keyof Views]?.trim() ? (
                  <div className="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed p-2 text-center text-xs text-muted-foreground">
                    <ImageOffIcon className="size-5" />
                    Shows the north view -- say what&apos;s on this side to draw
                    it
                  </div>
                ) : image.url ? (
                  <img
                    src={image.url}
                    alt={`${entry.name} -- ${image.label}`}
                    className="aspect-square w-full rounded-lg border bg-muted object-contain"
                  />
                ) : (
                  <div className="flex aspect-square w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed text-xs text-muted-foreground">
                    <ImageOffIcon className="size-5" />
                    Not drawn yet
                  </div>
                )}
                <p className="flex items-center gap-2 text-xs text-muted-foreground">
                  {image.label}
                  {image.sketched && <Badge variant="outline">Sketch</Badge>}
                </p>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">
            Save the {one} first -- then its images appear here.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {kind === "locations"
            ? "Each view is the location seen facing one compass direction, drawn from what's on that side the first time a shot needs it."
            : `Each reference is the ${one} seen from one side, drawn the first time a shot needs it.`}{" "}
          Sketching or generating them arrives in a later update.
        </p>
      </section>

      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="entry-name">Name</Label>
          <Input
            id="entry-name"
            autoFocus={!entry}
            required
            maxLength={MAX_NAME}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="entry-description">Description</Label>
          <Textarea
            id="entry-description"
            rows={5}
            maxLength={MAX_DESCRIPTION}
            placeholder={
              kind === "characters"
                ? "What they look like -- this is what their pictures are drawn from"
                : kind === "locations"
                  ? "What the whole place has in common -- what it's built of, its size and feel. What's on each side goes below."
                  : "What it looks like -- this is what its pictures are drawn from"
            }
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <p className="text-right text-xs text-muted-foreground">
            {description.length}/{MAX_DESCRIPTION}
          </p>
        </div>
        {kind === "locations" && (
          <>
            <div className="space-y-2">
              <Label htmlFor="entry-setting">Setting</Label>
              <EnumSelect
                id="entry-setting"
                value={setting}
                labels={SETTING_LABELS}
                onChange={setSetting}
              />
              {setting === "interior" && (
                <p className="text-xs text-muted-foreground">
                  Indoors, a scene&apos;s weather only changes the light -- rain
                  and snow are never drawn inside.
                </p>
              )}
            </div>
            <fieldset className="space-y-3">
              <legend className="text-sm font-medium">
                What&apos;s on each side
              </legend>
              {FACINGS.map((facing) => (
                <div key={facing} className="space-y-1">
                  <Label
                    htmlFor={`entry-view-${facing}`}
                    className="text-xs text-muted-foreground"
                  >
                    {FACING_LABELS[facing]}
                  </Label>
                  <Input
                    id={`entry-view-${facing}`}
                    maxLength={MAX_VIEW}
                    placeholder={
                      facing === "north"
                        ? "eg:- the back wall: a two-pane window behind a desk"
                        : "Empty shows the north view"
                    }
                    value={views[facing] ?? ""}
                    onChange={(e) =>
                      setViews((current) => ({
                        ...current,
                        [facing]: e.target.value,
                      }))
                    }
                  />
                </div>
              ))}
            </fieldset>
          </>
        )}
        {kind === "characters" && (
          <div className="space-y-2">
            <Label htmlFor="entry-aliases">Also known as</Label>
            <Input
              id="entry-aliases"
              placeholder="Other names, separated by commas"
              value={aliases}
              onChange={(e) => setAliases(e.target.value)}
            />
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        {saved && !error && (
          <p className="text-sm text-muted-foreground">Saved.</p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={saveEntry.isPending || !name.trim()}>
            {saveEntry.isPending
              ? "Saving..."
              : entry
                ? "Save"
                : `Create ${one}`}
          </Button>
          <Button type="button" variant="outline" onClick={onBack}>
            Back to all
          </Button>
          {entry && (
            <Button
              type="button"
              variant="destructive"
              className="ml-auto"
              onClick={() => onDelete(entry)}
            >
              <Trash2Icon />
              Delete
            </Button>
          )}
        </div>
      </form>
    </div>
  )
}
