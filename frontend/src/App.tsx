import { ProjectView } from "@/components/project-view"
import { StoryForm } from "@/components/story-form"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { configError } from "@/lib/api"
import { useProjectId } from "@/lib/navigation"
import { ProjectList } from "@/components/project-list"

export function App() {
  const [projectId, openProject] = useProjectId()

  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <button
            className="text-lg font-semibold"
            onClick={() => openProject(null)}
          >
            TaleBoard
          </button>
          {projectId && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => openProject(null)}
            >
              New story
            </Button>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">
        {configError ? (
          <Alert variant="destructive">
            <AlertTitle>Not configured</AlertTitle>
            <AlertDescription>{configError}</AlertDescription>
          </Alert>
        ) : projectId ? (
          <ProjectView key={projectId} projectId={projectId} />
        ) : (
          <div className="space-y-12">
            <StoryForm onStarted={openProject} />
            <ProjectList onOpen={openProject} />
          </div>
        )}
      </main>
    </div>
  )
}

export default App
