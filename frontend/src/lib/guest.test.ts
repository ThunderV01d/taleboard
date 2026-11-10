/**
 * Unit tests for browsing as a guest (lib/guest.ts): starting and ending the session, renewing its short-lived token
 * before it runs out, and telling listeners only when the session starts or ends.
 *
 * Run with: npm test
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  endGuestSession,
  guestAccessToken,
  isGuest,
  onGuestChange,
  startGuestSession,
} from "@/lib/guest"

/** Answers POST /auth/guest with token-1, token-2, ... each lasting `lifetime` seconds */
function fakeGuestRoute(lifetime = 900) {
  let issued = 0
  const route = vi.fn(async () => {
    issued += 1
    return new Response(
      JSON.stringify({
        access_token: `token-${issued}`,
        id_token: "id",
        expires_in: lifetime,
        token_type: "Bearer",
      }),
      { status: 200 }
    )
  })
  vi.stubGlobal("fetch", route)
  return route
}

beforeEach(() => endGuestSession())
afterEach(() => {
  endGuestSession()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe("the guest session", () => {
  it("starts with a token from POST /auth/guest, and ends", async () => {
    const route = fakeGuestRoute()

    await startGuestSession()

    expect(route).toHaveBeenCalledWith(
      expect.stringMatching(/\/auth\/guest$/),
      { method: "POST" }
    )
    expect(isGuest()).toBe(true)
    expect(await guestAccessToken()).toBe("token-1")
    endGuestSession()
    expect(isGuest()).toBe(false)
    expect(await guestAccessToken()).toBeNull()
  })

  it("gets a new token shortly before the old one runs out -- once, however many ask", async () => {
    vi.useFakeTimers()
    const route = fakeGuestRoute(900)
    await startGuestSession()

    vi.advanceTimersByTime(890_000) // Ten seconds left
    const tokens = await Promise.all([guestAccessToken(), guestAccessToken()])

    expect(tokens).toEqual(["token-2", "token-2"])
    expect(route).toHaveBeenCalledTimes(2)
  })

  it("tells listeners when it starts and ends, but not when its token is renewed", async () => {
    vi.useFakeTimers()
    fakeGuestRoute(900)
    const changes = vi.fn()
    const stop = onGuestChange(changes)

    await startGuestSession()
    vi.advanceTimersByTime(890_000)
    await guestAccessToken()
    endGuestSession()
    stop()

    expect(changes).toHaveBeenCalledTimes(2)
  })

  it("says why when there's no guest session to be had", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("", { status: 429 }))
    )

    await expect(startGuestSession()).rejects.toThrow(/try again/)
    expect(isGuest()).toBe(false)
  })
})
