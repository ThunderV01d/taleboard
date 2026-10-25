import { signIn } from "aws-amplify/auth"
import { useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router"

import { AuthCard, OrDivider } from "@/components/auth-card"
import { GoogleButton } from "@/components/google-button"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { authErrorMessage } from "@/lib/auth"

/** A message another page left for this one (eg:- "Email confirmed") */
type LoginState = { notice?: string } | null

/**
 * Sign in with Google, or with email and password.
 *
 * There's no navigating away on success here: once Amplify reports the sign-in, the page's guard
 * (RequireSignedOut) moves on to wherever the user was going.
 */
export function LoginPage() {
  const navigate = useNavigate()
  const notice = (useLocation().state as LoginState)?.notice
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const { nextStep } = await signIn({ username: email, password })
      if (nextStep.signInStep === "CONFIRM_SIGN_UP") {
        // Signed up earlier but never entered the emailed code -- finish that first
        navigate("/signup", { state: { confirmEmail: email } })
      } else if (nextStep.signInStep !== "DONE") {
        setError("This account needs a sign-in step TaleBoard doesn't support.")
      }
    } catch (e) {
      setError(authErrorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthCard
      title="Sign in"
      description="Welcome back to TaleBoard."
      footer={
        <span>
          Don't have an account?{" "}
          <Link to="/signup" className="text-foreground underline">
            Sign up
          </Link>
        </span>
      }
    >
      {notice && <p className="text-sm">{notice}</p>}
      <GoogleButton label="Sign in with Google" />
      <OrDivider />
      <form className="space-y-4" onSubmit={submit}>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button
          type="submit"
          variant="outline"
          className="w-full"
          disabled={busy}
        >
          {busy ? "Signing in..." : "Sign in"}
        </Button>
      </form>
    </AuthCard>
  )
}
