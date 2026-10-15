import { useEffect, useState } from "react"

const PROJECT_PARAM = "project"

function readProjectId(): string | null {
  return new URLSearchParams(window.location.search).get(PROJECT_PARAM)
}

/**
 * The open project's ID, kept in the URL (?project=...) so a refresh, a shared link or the back button keeps working.
 *
 * A query parameter rather than a path, so the static host needs no rewrite rules.
 */
export function useProjectId(): [
  string | null,
  (projectId: string | null) => void,
] {
  const [projectId, setProjectId] = useState(readProjectId)

  useEffect(() => {
    const onPopState = () => setProjectId(readProjectId())
    window.addEventListener("popstate", onPopState)
    return () => window.removeEventListener("popstate", onPopState)
  }, [])

  const openProject = (next: string | null) => {
    const url = new URL(window.location.href)
    if (next) {
      url.searchParams.set(PROJECT_PARAM, next)
    } else {
      url.searchParams.delete(PROJECT_PARAM)
    }
    window.history.pushState(null, "", url)
    setProjectId(next)
  }

  return [projectId, openProject]
}
