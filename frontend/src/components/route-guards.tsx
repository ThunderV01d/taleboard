import { Navigate, Outlet, useLocation } from "react-router"

import { useAuth } from "@/lib/auth-state"

/** Where a guard sent someone from, so they can be sent back after signing in */
type FromState = { from?: string } | null

/**
 * A short wait while Amplify checks for a saved session, so a signed-in user isn't bounced to the sign-in page on load.
 */
function CheckingSession() {
  return <p className="text-muted-foreground">Checking your session...</p>
}

/**
 * Pages only for signed-in users. Anyone else goes to the sign-in page, which sends them back here afterwards.
 */
export function RequireSignedIn() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.status === "loading") {
    return <CheckingSession />
  }
  if (auth.status === "signedOut") {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}

/**
 * Pages only for signed-out users (sign in, sign up). Signing in on one of them moves straight on -- to where the
 * user was going, or their projects.
 */
export function RequireSignedOut() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.status === "loading") {
    return <CheckingSession />
  }
  if (auth.status === "signedIn") {
    const from = (location.state as FromState)?.from
    return <Navigate to={from ?? "/projects"} replace />
  }
  return <Outlet />
}
