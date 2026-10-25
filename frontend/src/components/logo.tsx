import { cn } from "@/lib/utils"
import logoUrl from "@/assets/logo.svg"

/**
 * The TaleBoard wordmark, drawn in the current text colour -- so one image suits both the light and dark themes.
 *
 * The SVG is used as a mask over a block filled with currentColor: the logo's shapes let the colour through, and
 * everything else stays transparent. Size it with a height or width class; it keeps its 4:1 shape.
 */
export function Logo({ className }: { className?: string }) {
  const mask = `url("${logoUrl}") center / contain no-repeat`
  return (
    <span
      role="img"
      aria-label="TaleBoard"
      className={cn("inline-block aspect-[4/1] bg-current", className)}
      style={{ mask, WebkitMask: mask }}
    />
  )
}
