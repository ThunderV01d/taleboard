import {
  BrushIcon,
  EraserIcon,
  MousePointer2Icon,
  VectorSquareIcon,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** The canvas tools that work so far */
export type Tool = "select" | "distort"

const TOOLS: {
  id: Tool | "brush" | "eraser"
  label: string
  icon: typeof BrushIcon
}[] = [
  { id: "select", label: "Select and move (V)", icon: MousePointer2Icon },
  {
    id: "distort",
    label: "Distort -- drag a picture's corners (D)",
    icon: VectorSquareIcon,
  },
  { id: "brush", label: "Brush -- coming soon", icon: BrushIcon },
  { id: "eraser", label: "Eraser -- coming soon", icon: EraserIcon },
]

function isTool(id: string): id is Tool {
  return id === "select" || id === "distort"
}

/**
 * The tool strip down the left edge of the editor: Select and Distort, then the drawing tools still to come (shown
 * disabled, to mark where they'll go).
 */
export function ToolStrip({
  tool,
  onTool,
}: {
  tool: Tool
  onTool: (tool: Tool) => void
}) {
  return (
    <nav
      aria-label="Tools"
      className="flex flex-col items-center gap-1 border-r p-1.5"
    >
      {TOOLS.map(({ id, label, icon: Icon }) => (
        <Button
          key={id}
          variant="ghost"
          size="icon"
          title={label}
          aria-label={label}
          aria-pressed={id === tool}
          disabled={!isTool(id)}
          className={cn(id === tool && "bg-muted")}
          onClick={() => isTool(id) && onTool(id)}
        >
          <Icon />
        </Button>
      ))}
    </nav>
  )
}
