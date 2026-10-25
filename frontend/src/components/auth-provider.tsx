import { useQueryClient } from "@tanstack/react-query"
import { fetchAuthSession } from "aws-amplify/auth"
import { Hub } from "aws-amplify/utils"
import { useEffect, useState, type ReactNode } from "react"

import { AuthContext, type AuthState } from "@/lib/auth-state"

/**
 * Reads the signed-in user from Amplify's saved session.
 */
async function readSession(): Promise<AuthState> {
  try {
    const { tokens } = await fetchAuthSession()
    if (!tokens) {
      return { status: "signedOut" }
    }
    const email = tokens.idToken?.payload.email
    return { status: "signedIn", email: typeof email === "string" ? email : "" }
  } catch {
    return { status: "signedOut" }
  }
}

/**
 * Keeps the app's sign-in state in step with Amplify: checks for a saved session on load, then follows Amplify's
 * sign-in and sign-out events (from any page, or a Google redirect).
 *
 * Signing out also empties the query cache, so the next person on this browser never sees the last one's projects.
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
          refresh()
          break
        case "signedOut":
        case "tokenRefresh_failure":
          queryClient.clear()
          setState({ status: "signedOut" })
          break
      }
    })
    return () => {
      current = false
      stopListening()
    }
  }, [queryClient])

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>
}
