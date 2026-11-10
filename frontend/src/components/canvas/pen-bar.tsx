import { Label } from "@/components/ui/label"
import type { Pen } from "@/components/canvas/tool-strip"

/** Pen widths on offer, in frame pixels */
const WIDTHS = [1, 2, 4, 8, 16, 32, 64]

/**
 * The bar over the canvas while the brush or eraser is in use: the pen's colour (brush only) and width, and what a
 * stroke will do -- including, for the eraser with no drawing selected, why nothing happens.
 */
export function PenBar({
  tool,
  pen,
  onPen,
  hasDrawing,
}: {
  tool: "brush" | "eraser"
  pen: Pen
  onPen: (pen: Pen) => void
  /** Whether a drawing is selected (the brush starts a new one otherwise; the eraser needs one) */
  hasDrawing: boolean
}) {
  return (
    <div className="absolute top-1 left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full border bg-background/90 px-3 py-1 text-xs text-muted-foreground shadow-sm">
      {tool === "brush" && (
        <Label className="flex items-center gap-1.5 text-xs font-normal">
          Colour
          <input
            type="color"
            aria-label="Pen colour"
            className="size-5 cursor-pointer rounded border-0 bg-transparent p-0"
            value={pen.colour}
            onChange={(e) => onPen({ ...pen, colour: e.target.value })}
          />
        </Label>
      )}
      <Label className="flex items-center gap-1.5 text-xs font-normal">
        Width
        <select
          aria-label="Pen width"
          className="rounded border bg-background px-1 py-0.5"
          value={pen.width}
          onChange={(e) => onPen({ ...pen, width: Number(e.target.value) })}
        >
          {WIDTHS.map((width) => (
            <option key={width} value={width}>
              {width}
            </option>
          ))}
        </select>
      </Label>
      <span>
        {tool === "brush"
          ? hasDrawing
            ? "Drawing into the selected drawing."
            : "Your first stroke starts a new drawing."
          : hasDrawing
            ? "Rubbing out the selected drawing's strokes."
            : "Select a drawing to rub out part of it."}{" "}
        Esc or V to go back to Select.
      </span>
    </div>
  )
}
