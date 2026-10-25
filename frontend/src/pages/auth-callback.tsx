import { signInWithRedirect } from "aws-amplify/auth"
import { Hub } from "aws-amplify/utils"
import { useEffect, useState } from "react"
import { Link, Navigate } from "react-router"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { authErrorMessage, googleCallback } from "@/lib/auth"
import { useAuth } from "@/lib/auth-state"

/**
 * Cognito's error when a first Google sign-in has just been linked to an existing password account (by the
 * pre-sign-up trigger). The link is made, but this first attempt still fails -- trying again works.
 */
const LINK_QUIRK = "Already found an entry for username"

/** Remembers (for this tab) that the quirk has been retried once, so a different, real failure can't loop forever */
const RETRY_KEY = "taleboard:google-link-retried"

/**
 * Where Cognito sends the browser back after a Google sign-in. Amplify swaps the code in the address for tokens by
 * itself (see lib/auth.ts); this page waits for that, then moves on to the projects.
 *
 * If Cognito reports the account-linking quirk, it signs in with Google once more -- the user just sees a second,
 * quick redirect.
 */
export function AuthCallbackPage() {
  const auth = useAuth()
  const [failure, setFailure] = useState(googleCallback.error)
  const [canRetry] = useState(() => sessionStorage.getItem(RETRY_KEY) === null)
  const retrying = canRetry && (failure?.includes(LINK_QUIRK) ?? false)

  useEffect(
    () =>
      Hub.listen("auth", ({ payload }) => {
        if (payload.event === "signInWithRedirect_failure") {
          setFailure(authErrorMessage(payload.data.error))
        }
      }),
    []
  )

  useEffect(() => {
    if (retrying) {
      sessionStorage.setItem(RETRY_KEY, "yes")
      void signInWithRedirect({ provider: "Google" })
    }
  }, [retrying])

  useEffect(() => {
    if (auth.status === "signedIn") {
      sessionStorage.removeItem(RETRY_KEY)
    }
  }, [auth.status])

  if (auth.status === "signedIn") {
    return <Navigate to="/projects" replace />
  }
  if (failure && !retrying) {
    return (
      <Alert variant="destructive" className="mx-auto max-w-md">
        <AlertTitle>Google sign-in didn't work</AlertTitle>
        <AlertDescription>
          <p>{failure}</p>
          <Link to="/login" className="underline">
            Back to sign in
          </Link>
        </AlertDescription>
      </Alert>
    )
  }
  if (auth.status === "signedOut" && !googleCallback.hasCode && !failure) {
    // Arrived here without coming back from Google -- nothing to finish
    return <Navigate to="/login" replace />
  }
  return <p className="text-center text-muted-foreground">Signing you in...</p>
}
