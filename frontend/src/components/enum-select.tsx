import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

/**
 * A dropdown over one of the API's enums, showing each value's label (see lib/labels.ts).
 */
export function EnumSelect<T extends string>({
  id,
  value,
  labels,
  onChange,
}: {
  id?: string
  value: T
  labels: Record<T, string>
  onChange: (value: T) => void
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectTrigger id={id} className="w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {(Object.keys(labels) as T[]).map((option) => (
          <SelectItem key={option} value={option}>
            {labels[option]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
