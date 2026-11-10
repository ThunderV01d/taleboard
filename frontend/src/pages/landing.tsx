import { LoaderCircleIcon } from "lucide-react"
import { useEffect, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router"

import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth-state"
import { endGuestSession, startGuestSession } from "@/lib/guest"

/**
 * The front page: what TaleBoard is, and the way in -- or, once signed in, the way back to your projects. Without an
 * account, "Browse as guest" opens a few example projects, read-only -- and leaving them (the header's "Leave")
 * comes back here, which is where the guest session ends.
 */
export function LandingPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [starting, setStarting] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const leaving = (location.state as { leaveGuest?: boolean } | null)
    ?.leaveGuest
  useEffect(() => {
    if (leaving) {
      endGuestSession()
      void navigate(".", { replace: true, state: null })
    }
  }, [leaving, navigate])

  const browseAsGuest = async () => {
    setStarting(true)
    setProblem(null)
    try {
      await startGuestSession()
      void navigate("/projects")
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error))
    } finally {
      setStarting(false)
    }
  }

  return (
    <section className="mx-auto flex max-w-2xl flex-col items-center gap-8 py-16 text-center">
      <Logo className="h-20 sm:h-28" />
      <div className="space-y-4">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Take your stories and turn them into storyboards!
        </h1>
        <p className="text-lg text-muted-foreground">
          With full control of your shots, scenes, locations, characters and props. Don't want to use AI? TaleBoard allows you to do everything manually -- you are in control at all times.
        </p>
      </div>
      {/* One way in (the sign-in page also offers Google, which signs up too, and a link to sign up) -- or a look round first */}
      <div className="flex flex-wrap justify-center gap-3">
        <Button size="lg" asChild>
          {auth.status === "signedIn" ? (
            <Link to="/projects">My projects</Link>
          ) : (
            <Link to="/signup">Get started</Link>
          )}
        </Button>
        {auth.status === "guest" ? (
          <Button size="lg" variant="outline" asChild>
            <Link to="/projects">Example projects</Link>
          </Button>
        ) : auth.status === "signedOut" ? (
          <Button
            size="lg"
            variant="outline"
            disabled={starting}
            onClick={() => void browseAsGuest()}
          >
            {starting && <LoaderCircleIcon className="animate-spin" />}
            Browse as guest
          </Button>
        ) : null}
      </div>
      {problem && <p className="text-sm text-destructive">{problem}</p>}
    </section>
  )
}
