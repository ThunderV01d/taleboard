import { useState } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

/**
 * A labelled number box that only reports numbers it can parse -- so half-typed values like "-" or "1." don't reach
 * the layer -- and shows the latest value again whenever it isn't being typed into.
 */
export function NumberField({
  id,
  label,
  value,
  step = 1,
  min,
  max,
  decimals = 1,
  onChange,
}: {
  id: string
  label: string
  value: number
  step?: number
  min?: number
  max?: number
  /** How many decimal places to show */
  decimals?: number
  onChange: (value: number) => void
}) {
  const shown = String(Number(value.toFixed(decimals)))
  const [typed, setTyped] = useState<string | null>(null)

  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        step={step}
        min={min}
        max={max}
        className="h-8"
        value={typed ?? shown}
        onFocus={() => setTyped(shown)}
        onBlur={() => setTyped(null)}
        onChange={(event) => {
          setTyped(event.target.value)
          const parsed = Number(event.target.value)
          if (event.target.value.trim() !== "" && Number.isFinite(parsed)) {
            onChange(parsed)
          }
        }}
      />
    </div>
  )
}
