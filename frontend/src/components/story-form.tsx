import { useMutation } from "@tanstack/react-query"
import { useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { startStoryboard } from "@/lib/api"

/**
 * Takes a title and a story, and starts rendering it.
 */
export function StoryForm({
  onStarted,
}: {
  onStarted: (projectId: string) => void
}) {
  const [name, setName] = useState("")
  const [story, setStory] = useState("")
  const start = useMutation({
    mutationFn: () => startStoryboard(name.trim(), story),
    onSuccess: onStarted,
  })
  const canSubmit =
    name.trim() !== "" && story.trim() !== "" && !start.isPending

  return (
    <Card className="mx-auto max-w-2xl">
      <CardHeader>
        <CardTitle className="text-xl">New storyboard</CardTitle>
        <CardDescription>
          Paste a story, with a blank line between paragraphs. Each paragraph
          becomes one or more shots. Rendering takes a few minutes.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-5"
          onSubmit={(event) => {
            event.preventDefault()
            if (canSubmit) {
              start.mutate()
            }
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Title</Label>
            <Input
              id="name"
              value={name}
              maxLength={200}
              placeholder="The Lighthouse"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="story">Story</Label>
            <Textarea
              id="story"
              value={story}
              maxLength={100_000}
              className="min-h-72"
              placeholder="Mara climbed the last of the spiral stairs into the lamp room..."
              onChange={(event) => setStory(event.target.value)}
            />
          </div>
          {start.isError && (
            <Alert variant="destructive">
              <AlertTitle>Couldn't start the storyboard</AlertTitle>
              <AlertDescription>{start.error.message}</AlertDescription>
            </Alert>
          )}
          <Button type="submit" disabled={!canSubmit} className="self-start">
            {start.isPending ? "Starting..." : "Create storyboard"}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
