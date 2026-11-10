/**
 * A project's registries -- its characters, locations and props: queries and changes.
 *
 * The three registries share one API shape, so they share one set of functions here, picked by RegistryKind. The
 * API paths are spelled out per kind (rather than built from a string) so every call stays fully typed.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import type { components } from "@/api/schema"
import { api, unwrap } from "@/lib/api"
import { projectKeys } from "@/lib/projects"
import { scenesKey } from "@/lib/scenes"

type Schemas = components["schemas"]
export type Character = Schemas["CharacterOut"]
export type Location = Schemas["LocationOut"]
export type Prop = Schemas["PropOut"]
export type Entry = Character | Location | Prop
export type Usage = Schemas["Usage"]

/** The three registries, by their API path (and URL) segment */
export type RegistryKind = "characters" | "locations" | "props"

/** What a registry entry is called, singular and plural, in sentences and headings */
export const REGISTRY_NAMES: Record<
  RegistryKind,
  { one: string; many: string }
> = {
  characters: { one: "character", many: "Characters" },
  locations: { one: "location", many: "Locations" },
  props: { one: "prop", many: "Props" },
}

export function isRegistryKind(
  value: string | undefined
): value is RegistryKind {
  return value !== undefined && value in REGISTRY_NAMES
}

/** What's on each side of a location, by compass facing */
export type Views = Partial<Record<Schemas["Facing"], string>>

/** An entry's editable fields (aliases are characters' only; setting and views, locations') */
export type EntryFields = {
  name: string
  description: string
  aliases?: string[]
  setting?: Schemas["Setting"]
  views?: Views
}

/** What happens to a location's scenes when it's deleted */
export type ScenesChoice = { moveTo: string } | { deleteScenes: true }

/** Cache key for one registry -- under the project's, so deleting the project drops it */
export function registryKey(projectId: string, kind: RegistryKind) {
  return [...projectKeys.one(projectId), kind] as const
}

const path = (projectId: string) => ({ path: { project_id: projectId } })
const entryPath = (projectId: string, entryId: string) => ({
  path: { project_id: projectId, entry_id: entryId },
})

async function listEntries(
  projectId: string,
  kind: RegistryKind
): Promise<Entry[]> {
  switch (kind) {
    case "characters":
      return unwrap(
        await api.GET("/projects/{project_id}/characters", {
          params: path(projectId),
        })
      )
    case "locations":
      return unwrap(
        await api.GET("/projects/{project_id}/locations", {
          params: path(projectId),
        })
      )
    case "props":
      return unwrap(
        await api.GET("/projects/{project_id}/props", {
          params: path(projectId),
        })
      )
  }
}

async function createEntry(
  projectId: string,
  kind: RegistryKind,
  fields: EntryFields
): Promise<Entry> {
  const { aliases, setting, views, ...common } = fields
  switch (kind) {
    case "characters":
      return unwrap(
        await api.POST("/projects/{project_id}/characters", {
          params: path(projectId),
          body: { ...common, aliases: aliases ?? [] },
        })
      )
    case "locations":
      return unwrap(
        await api.POST("/projects/{project_id}/locations", {
          params: path(projectId),
          body: { ...common, setting: setting ?? "interior", views },
        })
      )
    case "props":
      return unwrap(
        await api.POST("/projects/{project_id}/props", {
          params: path(projectId),
          body: common,
        })
      )
  }
}

async function editEntry(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  fields: EntryFields
): Promise<Entry> {
  const { aliases, setting, views, ...common } = fields
  const params = entryPath(projectId, entryId)
  switch (kind) {
    case "characters":
      return unwrap(
        await api.PATCH("/projects/{project_id}/characters/{entry_id}", {
          params,
          body: { ...common, aliases: aliases ?? [] },
        })
      )
    case "locations":
      return unwrap(
        await api.PATCH("/projects/{project_id}/locations/{entry_id}", {
          params,
          body: { ...common, setting, views },
        })
      )
    case "props":
      return unwrap(
        await api.PATCH("/projects/{project_id}/props/{entry_id}", {
          params,
          body: common,
        })
      )
  }
}

async function entryUsage(
  projectId: string,
  kind: RegistryKind,
  entryId: string
): Promise<Usage> {
  const params = entryPath(projectId, entryId)
  switch (kind) {
    case "characters":
      return unwrap(
        await api.GET("/projects/{project_id}/characters/{entry_id}/usage", {
          params,
        })
      )
    case "locations":
      return unwrap(
        await api.GET("/projects/{project_id}/locations/{entry_id}/usage", {
          params,
        })
      )
    case "props":
      return unwrap(
        await api.GET("/projects/{project_id}/props/{entry_id}/usage", {
          params,
        })
      )
  }
}

async function deleteEntry(
  projectId: string,
  kind: RegistryKind,
  entryId: string,
  scenes: ScenesChoice
): Promise<Usage> {
  const params = entryPath(projectId, entryId)
  switch (kind) {
    case "characters":
      return unwrap(
        await api.DELETE("/projects/{project_id}/characters/{entry_id}", {
          params,
        })
      )
    case "props":
      return unwrap(
        await api.DELETE("/projects/{project_id}/props/{entry_id}", { params })
      )
    case "locations":
      return unwrap(
        await api.DELETE("/projects/{project_id}/locations/{entry_id}", {
          params: {
            ...params,
            query:
              "moveTo" in scenes
                ? { move_scenes_to: scenes.moveTo }
                : { delete_scenes: true },
          },
        })
      )
  }
}

/**
 * Every entry in one registry, by ID.
 */
export function useRegistry(projectId: string, kind: RegistryKind) {
  return useQuery({
    queryKey: registryKey(projectId, kind),
    queryFn: () => listEntries(projectId, kind),
  })
}

export function useCharacters(projectId: string) {
  return useQuery({
    queryKey: registryKey(projectId, "characters"),
    queryFn: () => listEntries(projectId, "characters") as Promise<Character[]>,
  })
}

export function useLocations(projectId: string) {
  return useQuery({
    queryKey: registryKey(projectId, "locations"),
    queryFn: () => listEntries(projectId, "locations") as Promise<Location[]>,
  })
}

export function useProps(projectId: string) {
  return useQuery({
    queryKey: registryKey(projectId, "props"),
    queryFn: () => listEntries(projectId, "props") as Promise<Prop[]>,
  })
}

/**
 * Where an entry is used -- the scenes (and, for characters and props, the shots) its delete would affect.
 */
export function useUsage(
  projectId: string,
  kind: RegistryKind,
  entryId: string
) {
  return useQuery({
    queryKey: [...registryKey(projectId, kind), entryId, "usage"],
    queryFn: () => entryUsage(projectId, kind, entryId),
    staleTime: 0,
  })
}

/**
 * Creates an entry, or edits one when given its ID. An edit can put the layers drawn from it out of date, so the
 * scenes and shots are refetched too.
 */
export function useSaveEntry(projectId: string, kind: RegistryKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      entryId,
      fields,
    }: {
      entryId?: string
      fields: EntryFields
    }) =>
      entryId
        ? editEntry(projectId, kind, entryId, fields)
        : createEntry(projectId, kind, fields),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: registryKey(projectId, kind),
          exact: true,
        }),
        queryClient.invalidateQueries({ queryKey: scenesKey(projectId) }),
      ]),
  })
}

/**
 * Deletes an entry. A character's or prop's layers go with it; a location's scenes are moved or deleted, as chosen.
 * Either way, scenes and shots elsewhere change, so they're refetched too.
 */
export function useDeleteEntry(projectId: string, kind: RegistryKind) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      entryId,
      scenes,
    }: {
      entryId: string
      scenes: ScenesChoice
    }) => deleteEntry(projectId, kind, entryId, scenes),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({
          queryKey: registryKey(projectId, kind),
        }),
        queryClient.invalidateQueries({ queryKey: scenesKey(projectId) }),
      ]),
  })
}

/**
 * An entry's images, with a label for each: a character's or prop's reference per orientation, or a location's plate
 * per facing (its slot). Missing ones (not drawn yet) are listed with no URL.
 */
export function entryImages(
  kind: RegistryKind,
  entry: Entry,
  labels: {
    orientations: Record<string, string>
    facings: Record<string, string>
  }
): {
  slot: Schemas["Orientation"] | Schemas["Facing"]
  label: string
  url: string | null
  sketched: boolean
}[] {
  if (kind === "locations") {
    const plates = (entry as Location).plates
    return Object.entries(labels.facings).map(([facing, label]) => {
      const plate = plates[facing]
      return {
        slot: facing as Schemas["Facing"],
        label,
        url: plate ? (entry.image_urls[plate.image] ?? null) : null,
        sketched: plate?.source === "sketch",
      }
    })
  }
  const references = (entry as Character | Prop).references
  return Object.entries(labels.orientations).map(([orientation, label]) => {
    const reference = references[orientation]
    return {
      slot: orientation as Schemas["Orientation"],
      label,
      url: reference ? (entry.image_urls[reference.image] ?? null) : null,
      sketched: reference?.source === "sketch",
    }
  })
}
