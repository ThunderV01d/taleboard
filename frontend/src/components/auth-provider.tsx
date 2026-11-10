import { useQueryClient } from "@tanstack/react-query"
import { fetchAuthSession } from "aws-amplify/auth"
import { Hub } from "aws-amplify/utils"
import { useEffect, useState, type ReactNode } from "react"

import { AuthContext, type AuthState } from "@/lib/auth-state"
import { endGuestSession, isGuest, onGuestChange } from "@/lib/guest"

/**
 * Reads the signed-in user from Amplify's saved session -- or, with none, whether this browser is browsing as the guest.
 */
async function readSession(): Promise<AuthState> {
  try {
    const { tokens } = await fetchAuthSession()
    if (tokens) {
      endGuestSession() // A real session never mixes with the guest's
      const email = tokens.idToken?.payload.email
      return {
        status: "signedIn",
        email: typeof email === "string" ? email : "",
      }
    }
  } catch {
    // No saved session
  }
  return isGuest() ? { status: "guest" } : { status: "signedOut" }
}

/**
 * Keeps the app's sign-in state in step with Amplify: checks for a saved session on load, then follows Amplify's
 * sign-in and sign-out events (from any page, or a Google redirect) -- and a guest session starting or ending.
 *
 * Signing in, signing out, and starting or leaving a guest session all empty the query cache, so nobody ever sees what
 * the last session loaded (a guest who signs up never sees the guest's projects as their own, nor the other way round).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [state, setState] = useState<AuthState>({ status: "loading" })

  useEffect(() => {
    let current = true
    const refresh = () =>
      void readSession().then((next) => current && setState(next))
    refresh()
    const stopListening = Hub.listen("auth", ({ payload }) => {
      switch (payload.event) {
        case "signedIn":
        case "signInWithRedirect":
          endGuestSession()
          queryClient.clear()
          refresh()
          break
        case "signedOut":
        case "tokenRefresh_failure":
          queryClient.clear()
          setState({ status: "signedOut" })
          break
      }
    })
    const stopFollowingGuest = onGuestChange(() => {
      queryClient.clear()
      refresh()
    })
    return () => {
      current = false
      stopListening()
      stopFollowingGuest()
    }
  }, [queryClient])

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}
