import { ScanIcon, ZoomInIcon, ZoomOutIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  FIT,
  MAX_ZOOM,
  MIN_ZOOM,
  ZOOM_STEP,
  zoomAt,
  type View,
} from "@/lib/zoom"

/**
 * Zooming the canvas, in the toolbar row: out, how large the frame is shown (100% is its own pixels), in, and fit.
 * The buttons zoom about the middle of the canvas; Ctrl and the wheel zoom about the pointer.
 */
export function ZoomBar({
  view,
  fitScale,
  onView,
}: {
  view: View
  /** Screen pixels per frame pixel when the frame is fitted -- what the percentage is worked out from */
  fitScale: number
  onView: (view: View) => void
}) {
  const fitted = view.zoom === FIT.zoom && view.x === FIT.x && view.y === FIT.y
  return (
    <div className="flex items-center gap-1">
      <Button
        variant="outline"
        size="icon-sm"
        title="Zoom out (Ctrl+-)"
        aria-label="Zoom out"
        disabled={view.zoom <= MIN_ZOOM}
        onClick={() => onView(zoomAt(view, view.zoom / ZOOM_STEP))}
      >
        <ZoomOutIcon />
      </Button>
      <span
        className="w-12 text-center text-sm text-muted-foreground tabular-nums"
        title="How large the frame is shown -- 100% is its own pixels"
        aria-live="polite"
      >
        {Math.round(fitScale * view.zoom * 100)}%
      </span>
      <Button
        variant="outline"
        size="icon-sm"
        title="Zoom in (Ctrl+=)"
        aria-label="Zoom in"
        disabled={view.zoom >= MAX_ZOOM}
        onClick={() => onView(zoomAt(view, view.zoom * ZOOM_STEP))}
      >
        <ZoomInIcon />
      </Button>
      <Button
        variant="outline"
        size="icon-sm"
        title="Fit the whole frame in view (Ctrl+0)"
        aria-label="Fit"
        disabled={fitted}
        onClick={() => onView(FIT)}
      >
        <ScanIcon />
      </Button>
    </div>
  )
}
