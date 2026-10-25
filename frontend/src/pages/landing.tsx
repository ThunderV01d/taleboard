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
          From story to storyboard
        </h1>
        <p className="text-lg text-muted-foreground">
          Break a story into scenes and shots, then block out every panel
          yourself: place characters, props and captions on a layered canvas,
          and only ask the AI to draw the parts you choose.
        </p>
      </div>
      {/* One way in: the sign-in page also offers Google (which signs up too) and a link to sign up */}
      <Button size="lg" asChild>
        {auth.status === "signedIn" ? (
          <Link to="/projects">My projects</Link>
        ) : (
          <Link to="/login">Get started</Link>
        )}
      </Button>
    </section>
  )
}
