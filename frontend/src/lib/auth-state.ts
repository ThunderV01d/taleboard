import { createContext, useContext } from "react"

/** Whether someone is signed in -- "loading" until Amplify has checked for a saved session */
export type AuthState =
  | { status: "loading" }
  | { status: "signedOut" }
  | { status: "signedIn"; email: string }

export const AuthContext = createContext<AuthState>({ status: "loading" })

/**
 * The current sign-in state (see AuthProvider).
 */
export function useAuth(): AuthState {
  return useContext(AuthContext)
}
