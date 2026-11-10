/**
 * The scene and shot last open in each project's editor, kept in the browser -- so leaving for a registry (or the
 * projects list) and coming back opens the same shot rather than the first one.
 *
 * A convenience only: it lives in this browser, and if storage is unavailable (a private window, blocked site data)
 * the editor just opens the first shot as before.
 */

/** Where the editor was in a project: its scene, and the shot within it (null for a scene with no shot open) */
export type LastShot = { scene: string; shot: string | null }

const key = (projectId: string) => `taleboard.lastShot.${projectId}`

export function readLastShot(projectId: string): LastShot | null {
  try {
    const stored = JSON.parse(localStorage.getItem(key(projectId)) ?? "null")
    return stored && typeof stored.scene === "string"
      ? {
          scene: stored.scene,
          shot: typeof stored.shot === "string" ? stored.shot : null,
        }
      : null
  } catch {
    return null
  }
}

export function writeLastShot(projectId: string, last: LastShot): void {
  try {
    localStorage.setItem(key(projectId), JSON.stringify(last))
  } catch {
    // Storage unavailable -- nothing to remember it in
  }
}
