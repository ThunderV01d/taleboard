import {
  DndContext,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragMoveEvent,
} from "@dnd-kit/core"
import {
  EyeIcon,
  EyeOffIcon,
  FolderIcon,
  GripVerticalIcon,
  ImageIcon,
  MountainIcon,
  PackageIcon,
  PenLineIcon,
  PlusIcon,
  Trash2Icon,
  TypeIcon,
  UserIcon,
} from "lucide-react"
import { useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { LAYER_TYPE_LABELS } from "@/lib/labels"
import {
  findLayer,
  type DropZone,
  type Layer,
  type LayerType,
} from "@/lib/layers"
import type { Character, Prop } from "@/lib/registries"
import { changesText, freshness } from "@/lib/staleness"
import { cn } from "@/lib/utils"

const ICONS: Record<LayerType, typeof UserIcon> = {
  background: MountainIcon,
  character: UserIcon,
  prop: PackageIcon,
  text: TypeIcon,
  image: ImageIcon,
  freehand: PenLineIcon,
  group: FolderIcon,
}

/** Where the dragged layer would land if dropped now */
type Drop = { targetId: string; zone: DropZone } | null

/**
 * The shot's (or sketch's) layers as a tree, top of the stack first (as image editors list them).
 *
 * Click a row to select it (shift- or ctrl-click to add to the selection). Drag a row by its grip:
 * - onto the top or bottom edge of another row to put it in front of or behind that layer (in that layer's group);
 * - onto the middle of a group to put it inside, on top;
 * - onto the middle of any other layer to make a new group of the two.
 *
 * A layer keeps its place on the canvas wherever it's dragged to in the tree. A generated layer whose picture is out of
 * date has an amber dot; one not drawn yet, a hollow one.
 */
export function LayersPanel({
  layers,
  selection,
  characters,
  props,
  registryLayers = true,
  outOfDate = {},
  readOnly = false,
  canAddBackground,
  onSelect,
  onToggleVisible,
  onDrop,
  onDelete,
  onAddBackground,
  onAddText,
  onAddImage,
  onAddGroup,
  onAddDrawing,
  onAddCharacter,
  onAddProp,
}: {
  layers: Layer[]
  selection: string[]
  characters: Character[]
  props: Prop[]
  /** Whether background, character and prop layers can be added (a shot's can; a sketch's can't). Defaults to true */
  registryLayers?: boolean
  /** The shot's out-of-date layers (as last saved), with what changed -- for the markers */
  outOfDate?: Record<string, string[]>
  /** Picking layers only -- no adding, deleting, dragging or hiding (a project shared to view) */
  readOnly?: boolean
  /** False while the shot already has its one background */
  canAddBackground: boolean
  onSelect: (ids: string[]) => void
  onToggleVisible: (id: string) => void
  onDrop: (draggedId: string, targetId: string, zone: DropZone) => void
  onDelete: () => void
  onAddBackground: () => void
  onAddText: () => void
  onAddImage: (file: File) => void
  onAddGroup: () => void
  onAddDrawing: () => void
  onAddCharacter: (character: Character) => void
  onAddProp: (prop: Prop) => void
}) {
  const file = useRef<HTMLInputElement>(null)
  const [drop, setDrop] = useState<Drop>(null)
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } })
  )

  const pick = (id: string, additive: boolean) =>
    onSelect(
      additive
        ? selection.includes(id)
          ? selection.filter((s) => s !== id)
          : [...selection, id]
        : [id]
    )

  /** Which part of the row under the pointer it's over: the top or bottom third, or the middle */
  const track = (event: DragMoveEvent) => {
    const over = event.over
    const start = event.activatorEvent as PointerEvent
    if (!over || over.id === event.active.id || !("clientY" in start)) {
      setDrop(null)
      return
    }
    const y = start.clientY + event.delta.y
    const position = (y - over.rect.top) / over.rect.height
    setDrop({
      targetId: String(over.id),
      zone: position < 0.3 ? "above" : position > 0.7 ? "below" : "onto",
    })
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Layers
        </h3>
        <input
          ref={file}
          type="file"
          accept="image/png,image/jpeg"
          className="hidden"
          onChange={(e) => {
            const chosen = e.target.files?.[0]
            e.target.value = ""
            if (chosen) {
              onAddImage(chosen)
            }
          }}
        />
        {!readOnly && (
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              title="Delete (Del)"
              aria-label="Delete the selected layers"
              disabled={selection.length === 0}
              onClick={onDelete}
            >
              <Trash2Icon />
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <PlusIcon />
                  Add
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {registryLayers && (
                  <DropdownMenuItem
                    disabled={!canAddBackground}
                    onSelect={onAddBackground}
                  >
                    <MountainIcon />
                    Background
                    {!canAddBackground && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        (has one)
                      </span>
                    )}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem onSelect={onAddText}>
                  <TypeIcon />
                  Text
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => file.current?.click()}>
                  <ImageIcon />
                  Image (upload)
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onAddDrawing}>
                  <PenLineIcon />
                  Drawing (empty)
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={onAddGroup}>
                  <FolderIcon />
                  Group (empty)
                </DropdownMenuItem>
                {registryLayers && (
                  <>
                    <DropdownMenuSeparator />
                    <RegistrySubmenu
                      label="Character"
                      icon={UserIcon}
                      entries={characters}
                      onPick={onAddCharacter}
                    />
                    <RegistrySubmenu
                      label="Prop"
                      icon={PackageIcon}
                      entries={props}
                      onPick={onAddProp}
                    />
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      {layers.length === 0 ? (
        <p className="rounded-md border border-dashed p-3 text-center text-xs text-muted-foreground">
          No layers -- add one above.
        </p>
      ) : (
        <DndContext
          sensors={sensors}
          onDragMove={track}
          onDragCancel={() => setDrop(null)}
          onDragEnd={(event) => {
            if (drop && findLayer(layers, String(event.active.id))) {
              onDrop(String(event.active.id), drop.targetId, drop.zone)
            }
            setDrop(null)
          }}
        >
          <ul className="rounded-md border p-1" role="tree" aria-label="Layers">
            <LayerRows
              layers={layers}
              depth={0}
              selection={selection}
              outOfDate={outOfDate}
              readOnly={readOnly}
              drop={drop}
              onPick={pick}
              onToggleVisible={onToggleVisible}
            />
          </ul>
        </DndContext>
      )}
      {!readOnly && (
        <p className="text-xs text-muted-foreground">
          Drag by the grip: onto a row's edge to reorder, onto its middle to
          group.
        </p>
      )}
    </div>
  )
}

/**
 * One level of the tree, top of the stack first; a group's children are listed under it, indented.
 */
function LayerRows({
  layers,
  depth,
  selection,
  outOfDate,
  readOnly,
  drop,
  onPick,
  onToggleVisible,
}: {
  layers: Layer[]
  depth: number
  selection: string[]
  outOfDate: Record<string, string[]>
  readOnly: boolean
  drop: Drop
  onPick: (id: string, additive: boolean) => void
  onToggleVisible: (id: string) => void
}) {
  return [...layers].reverse().map((layer) => (
    <li
      key={layer.id}
      role="treeitem"
      aria-selected={selection.includes(layer.id)}
    >
      <LayerRow
        layer={layer}
        depth={depth}
        selected={selection.includes(layer.id)}
        outOfDate={outOfDate}
        readOnly={readOnly}
        zone={drop?.targetId === layer.id ? drop.zone : null}
        onPick={onPick}
        onToggleVisible={onToggleVisible}
      />
      {layer.type === "group" && layer.children.length > 0 && (
        <ul role="group">
          <LayerRows
            layers={layer.children}
            depth={depth + 1}
            selection={selection}
            outOfDate={outOfDate}
            readOnly={readOnly}
            drop={drop}
            onPick={onPick}
            onToggleVisible={onToggleVisible}
          />
        </ul>
      )}
    </li>
  ))
}

/**
 * One layer's row: its grip (to drag), icon, name and visibility. It's also a drop target for other rows, and shows
 * where a dragged layer would land: a line along its top or bottom edge, or a highlight to go inside or group with it.
 */
function LayerRow({
  layer,
  depth,
  selected,
  outOfDate,
  readOnly,
  zone,
  onPick,
  onToggleVisible,
}: {
  layer: Layer
  depth: number
  selected: boolean
  outOfDate: Record<string, string[]>
  readOnly: boolean
  zone: DropZone | null
  onPick: (id: string, additive: boolean) => void
  onToggleVisible: (id: string) => void
}) {
  const {
    attributes,
    listeners,
    setNodeRef: setDragRef,
    setActivatorNodeRef,
    isDragging,
  } = useDraggable({ id: layer.id, disabled: readOnly })
  const { setNodeRef: setDropRef } = useDroppable({ id: layer.id })
  const Icon = ICONS[layer.type]
  const picture = freshness(layer, outOfDate)

  return (
    <div
      ref={(node) => {
        setDragRef(node)
        setDropRef(node)
      }}
      className={cn(
        "flex items-center gap-1 rounded-sm pr-1 text-sm",
        selected ? "bg-primary/10 text-foreground" : "hover:bg-muted",
        isDragging && "opacity-40",
        zone === "above" && "shadow-[inset_0_2px_0_0_var(--color-primary)]",
        zone === "below" && "shadow-[inset_0_-2px_0_0_var(--color-primary)]",
        zone === "onto" && "bg-primary/20 ring-1 ring-primary"
      )}
      style={{ paddingLeft: `${depth * 14 + 2}px` }}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        hidden={readOnly}
        aria-label={`Drag ${layer.name || LAYER_TYPE_LABELS[layer.type]}`}
        className="shrink-0 cursor-grab touch-none rounded p-0.5 text-muted-foreground hover:text-foreground active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVerticalIcon className="size-3.5" />
      </button>
      <button
        className="flex min-w-0 flex-1 items-center gap-2 py-1 text-left"
        onClick={(e) => onPick(layer.id, e.shiftKey || e.ctrlKey || e.metaKey)}
      >
        <Icon className="size-3.5 shrink-0 text-muted-foreground" />
        <span
          className={cn(
            "truncate",
            !layer.visible && "text-muted-foreground line-through"
          )}
        >
          {layer.name || LAYER_TYPE_LABELS[layer.type]}
        </span>
      </button>
      {picture?.state === "stale" && (
        <span
          role="img"
          aria-label="Out of date"
          title={`Out of date: ${changesText(picture.changes)} changed since it was drawn`}
          className="size-2 shrink-0 rounded-full bg-amber-500"
        />
      )}
      {picture?.state === "undrawn" && (
        <span
          role="img"
          aria-label="Not drawn yet"
          title="Not drawn yet"
          className="size-2 shrink-0 rounded-full border border-muted-foreground"
        />
      )}
      <button
        className="rounded p-1 text-muted-foreground hover:text-foreground"
        aria-label={layer.visible ? "Hide" : "Show"}
        disabled={readOnly}
        onClick={() => onToggleVisible(layer.id)}
      >
        {layer.visible ? (
          <EyeIcon className="size-3.5" />
        ) : (
          <EyeOffIcon className="size-3.5" />
        )}
      </button>
    </div>
  )
}

/**
 * "Add > Character" or "Add > Prop": the registry's entries, or a note that it's empty.
 */
function RegistrySubmenu<T extends { id: string; name: string }>({
  label,
  icon: Icon,
  entries,
  onPick,
}: {
  label: string
  icon: typeof UserIcon
  entries: T[]
  onPick: (entry: T) => void
}) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <Icon />
        {label}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        {entries.length === 0 ? (
          <DropdownMenuLabel className="font-normal text-muted-foreground">
            None in this project yet
          </DropdownMenuLabel>
        ) : (
          entries.map((entry) => (
            <DropdownMenuItem key={entry.id} onSelect={() => onPick(entry)}>
              {entry.name}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}
