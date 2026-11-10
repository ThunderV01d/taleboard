import { signOut } from "aws-amplify/auth"
import { Link, useMatch, useNavigate } from "react-router"

import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth-state"
import { useProject } from "@/lib/projects"
import { cn } from "@/lib/utils"

/**
 * The bar across the top of every page: the logo (home, or your projects once signed in), the open project's name in
 * the middle when there is one, and signing in or out -- or, for a guest, signing up or leaving.
 */
export function AppHeader() {
  const auth = useAuth()
  const navigate = useNavigate()
  // Any page inside a project -- the editor or one of its registries
  const inProject = useMatch("/projects/:projectId/*")
  const projectId = inProject?.params.projectId

  const leave = () => {
    // Leave the signed-in pages first, so their guard doesn't bounce to the sign-in page on the way out
    navigate("/")
    void signOut()
  }

  // The front page ends the guest session once it's showing -- ended here, the page being left would see a signed-out
  // visitor first, and send them to sign in
  const leaveGuest = () => navigate("/", { state: { leaveGuest: true } })
  const browsing = auth.status === "signedIn" || auth.status === "guest"

  return (
    <header className="shrink-0 border-b">
      <div
        className={cn(
          "mx-auto grid grid-cols-[1fr_auto_1fr] items-center gap-4 px-4 py-3",
          !projectId && "max-w-6xl"
        )}
      >
        <Link to={browsing ? "/projects" : "/"} className="justify-self-start">
          <Logo className="h-8" />
        </Link>
        <div className="min-w-0">
          {projectId && browsing && <ProjectTitle projectId={projectId} />}
        </div>
        <div className="justify-self-end">
          {auth.status === "signedIn" ? (
            <div className="flex items-center gap-3">
              <span className="hidden text-sm text-muted-foreground sm:inline">
                {auth.email}
              </span>
              <Button variant="outline" size="sm" onClick={leave}>
                Sign out
              </Button>
            </div>
          ) : auth.status === "guest" ? (
            <div className="flex items-center gap-3">
              <span className="hidden text-sm text-muted-foreground sm:inline">
                Guest
              </span>
              <Button size="sm" asChild>
                <Link to="/signup">Sign up</Link>
              </Button>
              <Button variant="outline" size="sm" onClick={leaveGuest}>
                Leave
              </Button>
            </div>
          ) : auth.status === "signedOut" ? (
            <Button variant="outline" size="sm" asChild>
              <Link to="/login">Sign in</Link>
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  )
}

/**
 * The open project's name, centred in the header (it links back to the project's editor from its registries).
 */
function ProjectTitle({ projectId }: { projectId: string }) {
  const project = useProject(projectId)
  return (
    <Link
      to={`/projects/${projectId}`}
      className="block max-w-[40vw] truncate text-center font-semibold hover:underline"
      title={project.data?.name}
    >
      {project.data?.name ?? ""}
    </Link>
  )
}
