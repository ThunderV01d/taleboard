import { Route, Routes, useMatch } from "react-router"

import { AppHeader } from "@/components/app-header"
import { RequireSignedIn, RequireSignedOut } from "@/components/route-guards"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { configError } from "@/lib/api"
import { authConfigError } from "@/lib/auth"
import { AuthCallbackPage } from "@/pages/auth-callback"
import { LandingPage } from "@/pages/landing"
import { LoginPage } from "@/pages/login"
import { NotFoundPage } from "@/pages/not-found"
import { ProjectEditorPage } from "@/pages/project-editor"
import { ProjectsPage } from "@/pages/projects"
import { RegistryPage } from "@/pages/registry"
import { SignUpPage } from "@/pages/sign-up"

const setupError = configError ?? authConfigError

export function App() {
  // The editor fills the window exactly (its panels scroll on their own); every other page is a centred column
  const inEditor = useMatch("/projects/:projectId") !== null
  return (
    <div
      className={inEditor ? "flex h-svh flex-col overflow-hidden" : "min-h-svh"}
    >
      <AppHeader />
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
            </Route>
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        )}
      </main>
    </div>
  )
}

export default App
