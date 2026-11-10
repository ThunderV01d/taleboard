import { Link, Route, Routes, useMatch } from "react-router"

import { AppHeader } from "@/components/app-header"
import { RequireSignedIn, RequireSignedOut } from "@/components/route-guards"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { configError } from "@/lib/api"
import { useAuth } from "@/lib/auth-state"
import { authConfigError } from "@/lib/auth"
import { AuthCallbackPage } from "@/pages/auth-callback"
import { LandingPage } from "@/pages/landing"
import { LoginPage } from "@/pages/login"
import { NotFoundPage } from "@/pages/not-found"
import { ProjectEditorPage } from "@/pages/project-editor"
import { ProjectsPage } from "@/pages/projects"
import { RegistryPage } from "@/pages/registry"
import { SignUpPage } from "@/pages/sign-up"
import { SketchPage } from "@/pages/sketch"

const setupError = configError ?? authConfigError

export function App() {
  // The editors (a project's, and the drawing pad) fill the window exactly (their panels scroll on their own); every
  // other page is a centred column
  const inProject = useMatch("/projects/:projectId") !== null
  const inSketch =
    useMatch("/projects/:projectId/:registry/:entryId/sketches/:slot") !== null
  const inEditor = inProject || inSketch
  return (
    <div
      className={inEditor ? "flex h-svh flex-col overflow-hidden" : "min-h-svh"}
    >
      <AppHeader />
      <GuestBanner />
      <main
        className={
          inEditor
            ? "flex min-h-0 flex-1 flex-col"
            : "mx-auto max-w-6xl px-4 py-8"
        }
      >
        {setupError ? (
          <Alert variant="destructive">
            <AlertTitle>Not configured</AlertTitle>
            <AlertDescription>{setupError}</AlertDescription>
          </Alert>
        ) : (
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route element={<RequireSignedOut />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<SignUpPage />} />
            </Route>
            <Route element={<RequireSignedIn />}>
              <Route path="/projects" element={<ProjectsPage />} />
              <Route
                path="/projects/:projectId"
                element={<ProjectEditorPage />}
              />
              <Route
                path="/projects/:projectId/:registry"
                element={<RegistryPage />}
              />
              <Route
                path="/projects/:projectId/:registry/:entryId/sketches/:slot"
                element={<SketchPage />}
              />
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        )}
      </main>
    </div>
  )
}

/**
 * A quiet strip under the header while browsing as a guest, pointing to signing up.
 */
function GuestBanner() {
  const auth = useAuth()
  if (auth.status !== "guest") {
    return null
  }
  return (
    <p className="shrink-0 border-b bg-muted/50 px-4 py-1.5 text-center text-sm text-muted-foreground">
      You&apos;re browsing as a guest --{" "}
      <Link to="/signup" className="font-medium text-foreground underline">
        sign up
      </Link>{" "}
      to make your own storyboards.
    </p>
  )
}

export default App
