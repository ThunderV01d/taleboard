import { useEffect, useSyncExternalStore } from "react"

/**
 * The canvas's pictures, each loaded once and kept for the session -- so opening a shot again (or one that shares an
 * image with the last) draws its pictures straight away, instead of flashing their placeholders while the browser
 * loads them again.
 *
 * A picture is known by its URL without the query string: every API response signs each image's URL afresh, but the
 * path (the image's key in the bucket) stays the same.
 */

type Entry = {
  /** The loaded picture -- null while it's loading, or if it failed */
  image: HTMLImageElement | null
  failed: boolean
  /** The URL it was loaded from (a failed load is tried again only from a different one) */
  url: string
}

/** How many pictures are kept; past that, the one used longest ago is let go */
const MAX_IMAGES = 200

const entries = new Map<string, Entry>()
const listeners = new Set<() => void>()

const idOf = (url: string) => url.split("?")[0]

function settle(id: string, loading: Entry, settled: Entry) {
  // Only if it's still the load asked for -- not let go, or started again since
  if (entries.get(id) === loading) {
    entries.set(id, settled)
    listeners.forEach((listener) => listener())
  }
}

/**
 * Starts loading a picture, unless it's loaded or loading already.
 */
export function loadImage(url: string): void {
  const id = idOf(url)
  const entry = entries.get(id)
  if (entry && !(entry.failed && entry.url !== url)) {
    // Used again: move it to the back of the queue to be let go
    entries.delete(id)
    entries.set(id, entry)
    return
  }
  const loading: Entry = { image: null, failed: false, url }
  entries.set(id, loading)
  while (entries.size > MAX_IMAGES) {
    entries.delete(entries.keys().next().value!)
  }
  const image = new Image()
  // "anonymous" so S3 sends CORS headers -- otherwise the canvas would be "tainted" and could never be exported
  image.crossOrigin = "anonymous"
  image.onload = () => settle(id, loading, { image, failed: false, url })
  image.onerror = () => settle(id, loading, { image: null, failed: true, url })
  image.src = url
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * A picture, once it has loaded -- straight away if it was loaded before, null until then (or if there's no URL).
 */
export function useLoadedImage(url: string | null): {
  image: HTMLImageElement | null
  failed: boolean
} {
  const id = url ? idOf(url) : null
  const entry = useSyncExternalStore(subscribe, () =>
    id ? entries.get(id) : undefined
  )
  useEffect(() => {
    if (url) {
      loadImage(url)
    }
  }, [url, entry])
  return { image: entry?.image ?? null, failed: entry?.failed ?? false }
}
