import { Link } from "react-router"

import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth-state"

/**
 * The front page: what TaleBoard is, and the way in -- or, once signed in, the way back to your projects.
 */
export function LandingPage() {
  const auth = useAuth()

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
      {/* One way in: the sign-in page also offers Google (which signs up too) and a link to sign up */}
      <Button size="lg" asChild>
        {auth.status === "signedIn" ? (
          <Link to="/projects">My projects</Link>
        ) : (
          <Link to="/signup">Get started</Link>
        )}
      </Button>
    </section>
  )
}
