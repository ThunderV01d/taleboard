/**
 * Sign-in through Amazon Cognito, using Amplify's Auth library (email + password, or Google).
 *
 * Importing this module configures Amplify, so it's imported first in main.tsx -- before anything signs in or calls the API.
 */
import { Amplify } from "aws-amplify"
// Finishes a Google sign-in when Cognito sends the browser back to /auth/callback with a code
import "aws-amplify/auth/enable-oauth-listener"

const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const userPoolClientId = import.meta.env.VITE_COGNITO_CLIENT_ID
const domain = import.meta.env.VITE_COGNITO_DOMAIN?.replace(/^https?:\/\//, "")

/** Where Cognito sends the browser back to after a Google sign-in (must be one of the app client's callback URLs) */
export const CALLBACK_PATH = "/auth/callback"

/** Set when the build is missing its Cognito settings, so the app can say so rather than fail every sign-in */
export const authConfigError =
  !userPoolId || !userPoolClientId || !domain
    ? "This build is missing VITE_COGNITO_USER_POOL_ID, VITE_COGNITO_CLIENT_ID or VITE_COGNITO_DOMAIN (see frontend/README.md)."
    : null

/**
 * What Cognito put in the address when it sent the browser back from Google -- read before Amplify tidies the address up.
 *
 * Amplify starts handling the callback as soon as it's configured (below), so this has to be captured first.
 */
export const googleCallback = (() => {
  if (window.location.pathname !== CALLBACK_PATH) {
    return { hasCode: false, error: null }
  }
  const params = new URLSearchParams(window.location.search)
  return { hasCode: params.has("code"), error: params.get("error_description") }
})()

if (!authConfigError) {
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        signUpVerificationMethod: "code",
        loginWith: {
          email: true,
          oauth: {
            domain,
            scopes: ["openid", "email", "profile"],
            redirectSignIn: [`${window.location.origin}${CALLBACK_PATH}`],
            redirectSignOut: [`${window.location.origin}/`],
            responseType: "code",
          },
        },
      },
    },
  })
}

/**
 * Turns an Amplify sign-in error into a sentence to show the user.
 */
export function authErrorMessage(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Something went wrong -- please try again."
  }
  if (error.name === "UsernameExistsException") {
    return "There's already an account with this email -- sign in instead."
  }
  // The pre-sign-up trigger's own message (eg:- the email already signs in with Google), without Cognito's prefix
  return error.message.replace(/^PreSignUp failed with error /, "")
}
