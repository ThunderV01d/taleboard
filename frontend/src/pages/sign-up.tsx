import {
  autoSignIn,
  confirmSignUp,
  resendSignUpCode,
  signUp,
} from "aws-amplify/auth"
import { useState, type FormEvent } from "react"
import { Link, useLocation, useNavigate } from "react-router"

import { AuthCard, OrDivider } from "@/components/auth-card"
import { GoogleButton } from "@/components/google-button"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { authErrorMessage } from "@/lib/auth"

/** Must match the user pool's password policy (infra/taleboard_stack.py) */
const MIN_PASSWORD_LENGTH = 10

/** Set by the sign-in page when an account exists but its email was never confirmed */
type SignUpState = { confirmEmail?: string } | null

/**
 * Create an account: with Google, or with email and password -- then confirm the email with the code Cognito sends.
 *
 * Signing up here signs in automatically once the code is confirmed. An account confirmed later (arriving from the
 * sign-in page) has no password to hand, so that path goes back to sign in.
 */
export function SignUpPage() {
  const navigate = useNavigate()
  const confirmEmail = (useLocation().state as SignUpState)?.confirmEmail
  const [stage, setStage] = useState<"details" | "confirm">(
    confirmEmail ? "confirm" : "details"
  )
  const [email, setEmail] = useState(confirmEmail ?? "")
  const [password, setPassword] = useState("")
  const [code, setCode] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  /** Runs one Amplify call, showing its error if it fails */
  const attempt = async (action: () => Promise<void>) => {
    setError(null)
    setNotice(null)
    setBusy(true)
    try {
      await action()
    } catch (e) {
      setError(authErrorMessage(e))
    } finally {
      setBusy(false)
    }
  }

  const submitDetails = (event: FormEvent) => {
    event.preventDefault()
    void attempt(async () => {
      const { nextStep } = await signUp({
        username: email,
        password,
        options: { userAttributes: { email }, autoSignIn: true },
      })
      if (nextStep.signUpStep === "CONFIRM_SIGN_UP") {
        setStage("confirm")
      } else if (nextStep.signUpStep === "COMPLETE_AUTO_SIGN_IN") {
        await autoSignIn()
      }
    })
  }

  const submitCode = (event: FormEvent) => {
    event.preventDefault()
    void attempt(async () => {
      const { nextStep } = await confirmSignUp({
        username: email,
        confirmationCode: code.trim(),
      })
      if (nextStep.signUpStep === "COMPLETE_AUTO_SIGN_IN") {
        await autoSignIn() // The page's guard then moves on to the projects
      } else {
        navigate("/login", {
          state: { notice: "Email confirmed -- sign in to carry on." },
        })
      }
    })
  }

  const resend = () =>
    void attempt(async () => {
      await resendSignUpCode({ username: email })
      setNotice(`A new code is on its way to ${email}.`)
    })

  if (stage === "confirm") {
    return (
      <AuthCard
        title="Confirm your email"
        description={`Enter the code we sent to ${email}. It can take a minute to arrive -- check your spam folder too.`}
      >
        <form className="space-y-4" onSubmit={submitCode}>
          <div className="space-y-2">
            <Label htmlFor="code">Confirmation code</Label>
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          {error && <p className="text-sm text-destructive">{error}</p>}
          {notice && <p className="text-sm">{notice}</p>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Confirming..." : "Confirm"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="w-full"
            disabled={busy}
            onClick={resend}
          >
            Send a new code
          </Button>
        </form>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Create an account"
      description="Start turning stories into storyboards."
      footer={
        <span>
          Already have an account?{" "}
          <Link to="/login" className="text-foreground underline">
            Sign in
          </Link>
        </span>
      }
    >
      <GoogleButton label="Sign up with Google" />
      <OrDivider />
      <form className="space-y-4" onSubmit={submitDetails}>
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
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            At least {MIN_PASSWORD_LENGTH} characters.
          </p>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button
          type="submit"
          variant="outline"
          className="w-full"
          disabled={busy}
        >
          {busy ? "Creating your account..." : "Create account"}
        </Button>
      </form>
    </AuthCard>
  )
}
