"""
Routes for the three registries -- characters, props and locations. One factory (registry_router) builds the same routes for each, so they can't drift apart.

Deleting a character or prop also removes every layer showing it. Deleting a location needs a decision about its scenes -- move them to another location, or delete them -- given as a query parameter.

Each entry can also have a sketch for any of its slots (a character's or prop's orientations, a location's facings): a layer graph the user draws, saved like a shot. The browser flattens it into an upload, and using that upload makes it the slot's reference (or plate) -- until the user goes back to the generated one.

Attributes:
    characters: APIRouter - Routes for the character registry.
    props: APIRouter - Routes for the prop registry.
    locations: APIRouter - Routes for the location registry.
"""
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError

from taleboard.api.deps import get_boards, get_project, image_urls, not_found
from taleboard.schema.enums import Facing, Orientation, Setting
from taleboard.schema.layers import Layer
from taleboard.schema.storyboard import SKETCH_FRAMES, Character, Location, Project, Prop, Reference, Sketch, View, flatten
from taleboard.storage.cascades import Usage, delete_entry_and_uses, delete_location, find_usage
from taleboard.storage.storyboard_store import StoryboardStore


class EntryIn(BaseModel):
    """
    Request body for creating a prop or location.

    Attributes:
        name: str - Name of the entry (its ID is made from this, once).
        description: str - What it looks like, in words. Defaults to "".
    """
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=300)

class CharacterIn(EntryIn):
    """
    Request body for creating a character.

    Attributes:
        aliases: list[str] - Other ways the story refers to them. Defaults to [].
    """
    aliases: list[str] = Field(default_factory=list)

class LocationIn(EntryIn):
    """
    Request body for creating a location.

    Attributes:
        setting: Setting - Whether the place is indoors or out. Defaults to INT.
        views: dict[Facing,str] - What's on each side of the place. Defaults to {}.
    """
    setting: Setting = Setting.INT
    views: dict[Facing, View] = Field(default_factory=dict)

class EntryPatch(BaseModel):
    """
    Request body for editing a prop or location. Only the fields sent are changed; the ID never is, even if the name is.

    Attributes:
        name: str - New name. Defaults to None (unchanged).
        description: str - New description. Defaults to None (unchanged).
    """
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)

class CharacterPatch(EntryPatch):
    """
    Request body for editing a character.

    Attributes:
        aliases: list[str] - New aliases (replacing the old ones). Defaults to None (unchanged).
    """
    aliases: list[str] | None = None

class LocationPatch(EntryPatch):
    """
    Request body for editing a location.

    Attributes:
        setting: Setting - New setting. Defaults to None (unchanged).
        views: dict[Facing,str] - New views (replacing the old ones). Defaults to None (unchanged).
    """
    setting: Setting | None = None
    views: dict[Facing, View] | None = None

class CharacterOut(Character):
    """
    A character, with a download URL for each of their reference images.

    Attributes:
        image_urls: dict[str,str] - Download URL for each image key in the entry.
    """
    image_urls: dict[str, str] = Field(default_factory=dict)

class PropOut(Prop):
    """
    A prop, with a download URL for each of its reference images.

    Attributes:
        image_urls: dict[str,str] - Download URL for each image key in the entry.
    """
    image_urls: dict[str, str] = Field(default_factory=dict)

class LocationOut(Location):
    """
    A location, with a download URL for each of its plates.

    Attributes:
        image_urls: dict[str,str] - Download URL for each image key in the entry.
    """
    image_urls: dict[str, str] = Field(default_factory=dict)


def _image_keys(entry: Character | Prop | Location) -> list[str]:
    """
    Every S3 image key an entry holds: a location's plates, or a character's or prop's references.

    Arguments:
        entry: Character|Prop|Location - The entry.

    Returns:
        list[str] - Its image keys.
    """
    if isinstance(entry, Location):
        return [plate.image for plate in entry.plates.values()]
    return [reference.image for reference in entry.references.values()]

class SketchSave(BaseModel):
    """
    Request body for saving a sketch.

    Attributes:
        layers: list[Layer] - The layer graph, bottom to top.
        version: int - The version the editor loaded (0 for a sketch not saved before).
    """
    layers: list[Layer]
    version: int = Field(ge=0)

class SketchOut(Sketch):
    """
    A sketch, with a download URL for each of its layers' images.

    Attributes:
        image_urls: dict[str,str] - Download URL for each image key in the sketch.
    """
    image_urls: dict[str, str] = Field(default_factory=dict)

class SketchUse(BaseModel):
    """
    Request body for using a flattened sketch as a slot's image.

    Attributes:
        image: str - S3 key of the flattened sketch -- an upload of this project's.
        remove_background: bool - For a character or prop, whether its background is cut away before it's drawn from. Defaults to True.
    """
    image: str
    remove_background: bool = True


def registry_router(path: str, model: type, in_model: type[EntryIn], patch_model: type[EntryPatch], out_model: type, slot_type: type[Enum]) -> APIRouter:
    """
    Builds one registry's routes: list, create, read, edit, usage and delete -- and each entry's sketches.

    Arguments:
        path: str - URL segment of the registry (eg:- "characters").
        model: type - Character, Prop or Location.
        in_model: type - Request body for creating an entry.
        patch_model: type - Request body for editing an entry.
        out_model: type - Response shape of an entry (with its image URLs).
        slot_type: type - What an entry's images are kept by: Orientation, or Facing for locations.

    Returns:
        APIRouter - The registry's routes, under /projects/{project_id}/{path}.
    """
    router = APIRouter(prefix=f"/projects/{{project_id}}/{path}", tags=[path])

    def load(boards: StoryboardStore, project: Project, entry_id: str):
        try:
            return boards.get_entry(project.project_id, model, entry_id)
        except KeyError as error:
            raise not_found(error) from None

    def out(boards: StoryboardStore, project: Project, entry):
        return out_model(**entry.model_dump(), image_urls=image_urls(boards, project.project_id, _image_keys(entry)))

    @router.get("", response_model=list[out_model])
    def list_entries(project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Lists every entry in the registry, by ID."""
        return [out(boards, project, entry) for entry in boards.list_entries(project.project_id, model)]

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=out_model)
    def create_entry(body: in_model, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Adds an entry, with an ID made from its name (suffixed if that's taken)."""
        return out(boards, project, boards.create_entry(project.project_id, model, **body.model_dump()))

    @router.get("/{entry_id}", response_model=out_model)
    def read_entry(entry_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Gets one entry."""
        return out(boards, project, load(boards, project, entry_id))

    @router.patch("/{entry_id}", response_model=out_model)
    def edit_entry(entry_id: str, body: patch_model, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Changes the fields sent, keeping everything else -- its ID and images included."""
        edited = load(boards, project, entry_id).model_copy(update=body.model_dump(exclude_none=True))
        boards.save_entry(project.project_id, edited)
        return out(boards, project, edited)

    def slots(entry) -> dict:
        return entry.plates if isinstance(entry, Location) else entry.references

    def sketch_out(boards: StoryboardStore, project: Project, sketch: Sketch) -> SketchOut:
        keys = (getattr(layer, "image", None) for layer in flatten(sketch.layers))
        return SketchOut(**sketch.model_dump(), image_urls=image_urls(boards, project.project_id, keys))

    @router.get("/{entry_id}/sketches/{slot}", response_model=SketchOut)
    def read_sketch(entry_id: str, slot: slot_type, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Gets the entry's sketch for one slot -- a 404 if it has none."""
        load(boards, project, entry_id)
        try:
            return sketch_out(boards, project, boards.get_sketch(project.project_id, model, entry_id, slot.value))
        except KeyError as error:
            raise not_found(error) from None

    @router.put("/{entry_id}/sketches/{slot}", response_model=SketchOut)
    def save_sketch(entry_id: str, slot: slot_type, body: SketchSave, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Saves the entry's sketch for one slot (creating it at version 0) -- refused with a 409 if it has been saved since the version sent."""
        load(boards, project, entry_id)
        width, height = SKETCH_FRAMES[path]
        try:
            sketch = Sketch(registry=path, entry_id=entry_id, slot=slot.value, width=width, height=height, **body.model_dump())
        except ValidationError as error:
            raise RequestValidationError(error.errors(include_url=False, include_context=False)) from None
        return sketch_out(boards, project, boards.save_sketch(project.project_id, model, sketch))

    @router.put("/{entry_id}/sketches/{slot}/use", response_model=out_model)
    def use_sketch(entry_id: str, slot: slot_type, body: SketchUse, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Makes a flattened sketch (one of this project's uploads) the slot's image -- every layer drawn from it is then out of date."""
        if not body.image.startswith(f"projects/{project.project_id}/uploads/"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A sketch must be one of this project's uploads")
        entry = load(boards, project, entry_id)
        slots(entry)[slot] = Reference(image=body.image, source="sketch", remove_background=body.remove_background)
        boards.save_entry_image(project.project_id, entry, slot.value)
        return out(boards, project, entry)

    @router.delete("/{entry_id}/sketches/{slot}/use", response_model=out_model)
    def stop_using_sketch(entry_id: str, slot: slot_type, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Goes back to a generated image for the slot (drawn when it's next needed; the sketch itself is kept). Nothing changes if it isn't using a sketch."""
        entry = load(boards, project, entry_id)
        current = slots(entry).get(slot)
        if current is not None and current.source == "sketch":
            boards.clear_entry_image(project.project_id, entry, slot.value)
            del slots(entry)[slot]
        return out(boards, project, entry)

    @router.get("/{entry_id}/usage", response_model=Usage)
    def entry_usage(entry_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
        """Where the entry is used -- what the delete confirmation lists."""
        load(boards, project, entry_id)  # A 404 if there's no such entry
        return find_usage(boards, project.project_id, model, entry_id)

    if model is Location:
        @router.delete("/{entry_id}", response_model=Usage)
        def delete_entry(
            entry_id: str,
            move_scenes_to: str | None = Query(default=None, description="Location to move this location's scenes to"),
            delete_scenes: bool = Query(default=False, description="Delete this location's scenes (and their shots) instead"),
            project: Project = Depends(get_project),
            boards: StoryboardStore = Depends(get_boards),
        ):
            """Deletes a location, after moving or deleting its scenes -- exactly one of the two must be asked for."""
            if (move_scenes_to is not None) == delete_scenes:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Say what happens to this location's scenes: either move_scenes_to or delete_scenes=true")
            try:
                return delete_location(boards, project.project_id, entry_id, move_scenes_to=move_scenes_to)
            except KeyError as error:
                raise not_found(error) from None
            except ValueError as error:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    else:
        @router.delete("/{entry_id}", response_model=Usage)
        def delete_entry(entry_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)):
            """Deletes the entry, and every layer showing it."""
            try:
                return delete_entry_and_uses(boards, project.project_id, model, entry_id)
            except KeyError as error:
                raise not_found(error) from None

    return router


characters = registry_router("characters", Character, CharacterIn, CharacterPatch, CharacterOut, Orientation)
props = registry_router("props", Prop, EntryIn, EntryPatch, PropOut, Orientation)
locations = registry_router("locations", Location, LocationIn, LocationPatch, LocationOut, Facing)