import {
  BrushIcon,
  EraserIcon,
  MousePointer2Icon,
  VectorSquareIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** The canvas tools */
export type Tool = "select" | "distort" | "brush" | "eraser"

/** What the brush and eraser draw with: colour (#rrggbb) and width (in frame pixels) */
export type Pen = { colour: string; width: number }

const TOOLS: { id: Tool; label: string; icon: typeof BrushIcon }[] = [
  { id: "select", label: "Select and move (V)", icon: MousePointer2Icon },
  {
    id: "distort",
    label: "Distort -- drag a picture's or drawing's corners (D)",
    icon: VectorSquareIcon,
  },
  {
    id: "brush",
    label: "Brush -- draw into the selected drawing, or a new one (B)",
    icon: BrushIcon,
  },
  {
    id: "eraser",
    label: "Eraser -- rub out part of the selected drawing (E)",
    icon: EraserIcon,
  },
]

/**
 * The tool strip down the left edge of the editor: Select, Distort, the brush and the eraser -- only Select, when the
 * project is read-only.
 */
export function ToolStrip({
  tool,
  onTool,
  readOnly = false,
}: {
  tool: Tool
  onTool: (tool: Tool) => void
  readOnly?: boolean
}) {
  return (
    <nav
      aria-label="Tools"
      className="flex flex-col items-center gap-1 border-r p-1.5"
    >
      {TOOLS.filter(({ id }) => !readOnly || id === "select").map(
        ({ id, label, icon: Icon }) => (
          <Button
            key={id}
            variant="ghost"
            size="icon"
            title={label}
            aria-label={label}
            aria-pressed={id === tool}
            className={cn(id === tool && "bg-muted")}
            onClick={() => onTool(id)}
          >
            <Icon />
          </Button>
        )
      )}
    </nav>
  )
}
