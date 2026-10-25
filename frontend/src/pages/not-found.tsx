import { Link } from "react-router"

/**
 * Any address the app doesn't know.
 */
export function NotFoundPage() {
  return (
    <section className="space-y-2">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">
        There's nothing here.{" "}
        <Link to="/" className="underline">
          Back to the start
        </Link>
      </p>
    </section>
  )
}
