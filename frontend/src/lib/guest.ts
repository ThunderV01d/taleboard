/**
 * Browsing as a guest: a session for the shared, read-only guest user, kept apart from Amplify's.
 *
 * The API hands out the guest's tokens (POST /auth/guest, which needs no sign-in). They're short-lived and come without
 * a refresh token, so instead of refreshing, a new pair is asked for shortly before they run out. Amplify can't be
 * given tokens from elsewhere, so the guest's are kept here, in this browser (like Amplify's own), and the API client
 * uses them whenever nobody is signed in through Amplify.
 *
 * Signing in or up ends the guest session (see AuthProvider), so a real session never mixes with the guest's.
 */
const apiUrl = import.meta.env.VITE_API_URL?.replace(/\/+$/, "")

const KEY = "taleboard.guest"

/** Ask for new tokens this long before the old ones run out, so a request never goes out with one about to expire */
const RENEW_EARLY_MS = 60_000

type GuestSession = { accessToken: string; idToken: string; expiresAt: number }

const listeners = new Set<() => void>()
let renewing: Promise<string> | null = null
// The session in memory too, for when storage is unavailable (a private window, blocked site data)
let memory: GuestSession | null = null

function read(): GuestSession | null {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) ?? "null")
    return stored && typeof stored.accessToken === "string" ? stored : null
  } catch {
    return null
  }
}

/**
 * Keeps (or, with null, forgets) the guest session -- telling the listeners only when browsing as the guest starts or
 * stops, not when its tokens are renewed.
 */
function write(session: GuestSession | null): void {
  const was = isGuest()
  try {
    if (session) {
      localStorage.setItem(KEY, JSON.stringify(session))
    } else {
      localStorage.removeItem(KEY)
    }
  } catch {
    // Storage unavailable -- the session then lasts only as long as the page (see `memory`)
  }
  memory = session
  if (was !== (session !== null)) {
    listeners.forEach((listener) => listener())
  }
}

/** Whether this browser is browsing as the guest */
export function isGuest(): boolean {
  return (read() ?? memory) !== null
}

/** Asks the API for a new pair of guest tokens, and keeps them */
async function fetchTokens(): Promise<string> {
  const response = await fetch(`${apiUrl}/auth/guest`, { method: "POST" })
  if (!response.ok) {
    throw new Error(
      response.status === 429
        ? "Lots of people are browsing right now -- please try again in a moment."
        : "Guest browsing isn't available right now -- please try again later."
    )
  }
  const body = (await response.json()) as {
    access_token: string
    id_token: string
    expires_in: number
  }
  write({
    accessToken: body.access_token,
    idToken: body.id_token,
    expiresAt: Date.now() + body.expires_in * 1000,
  })
  return body.access_token
}

/**
 * Gets new guest tokens -- one request however many callers ask at once.
 */
export function renewGuestSession(): Promise<string> {
  renewing ??= fetchTokens().finally(() => {
    renewing = null
  })
  return renewing
}

/**
 * Starts browsing as the guest. Throws, with a message to show, if the guest tokens can't be had.
 */
export async function startGuestSession(): Promise<void> {
  await renewGuestSession()
}

/**
 * The guest's access token, renewed first if it's about to run out -- or null when not browsing as the guest.
 */
export async function guestAccessToken(): Promise<string | null> {
  const session = read() ?? memory
  if (!session) {
    return null
  }
  return session.expiresAt - Date.now() > RENEW_EARLY_MS
    ? session.accessToken
    : renewGuestSession()
}

/** Stops browsing as the guest, forgetting its tokens */
export function endGuestSession(): void {
  if (isGuest()) {
    write(null)
  }
}

/**
 * Calls `listener` whenever a guest session starts or ends. Returns a function that stops it.
 */
export function onGuestChange(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
