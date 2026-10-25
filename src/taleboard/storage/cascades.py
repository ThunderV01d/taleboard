"""
What deleting part of a project does to the rest of it: finding where a registry entry is used (for the confirmation popup), and removing those uses along with the entry.

Characters and props are used by layers, so deleting one removes every layer showing it. Locations are used by whole scenes, so deleting one either moves those scenes to another location or deletes them (see delete_location).

Attributes:
    SAVE_ATTEMPTS: int - How many times a shot is reloaded and edited again if it is saved by someone else in the middle of a deletion.
"""
from pydantic import Field

from taleboard.schema.base import Model
from taleboard.schema.layers import CharacterLayer, GroupLayer, Layer, PropLayer
from taleboard.schema.storyboard import Character, Location, Prop
from taleboard.storage.storyboard_store import ShotConflictError, StoryboardStore

SAVE_ATTEMPTS = 3


class ShotUse(Model):
    """
    One shot that uses a registry entry.

    Attributes:
        shot_id: str - Unique ID of the shot.
        order: int - Position of the shot in its scene.
    """
    shot_id: str
    order: int

class SceneUse(Model):
    """
    One scene that uses a registry entry, with the shots in it that do.

    Attributes:
        scene_id: str - Unique ID of the scene.
        name: str - Name of the scene.
        order: int - Position of the scene in the project.
        shots: list[ShotUse] - The scene's shots that use the entry, in order.
    """
    scene_id: str
    name: str
    order: int
    shots: list[ShotUse] = Field(default_factory=list)

class Usage(Model):
    """
    Everywhere a registry entry is used -- what the delete confirmation lists, and what deleting it takes with it.

    Attributes:
        scenes: list[SceneUse] - Scenes using the entry, in story order. Defaults to [] (unused).
    """
    scenes: list[SceneUse] = Field(default_factory=list)

    @property
    def shot_count(self) -> int:
        """
        How many shots use the entry, across every scene.

        Returns:
            int - Number of shots.
        """
        return sum(len(scene.shots) for scene in self.scenes)

# Which layer type shows each kind of registry entry, and the field holding its ID
_LAYER_REFERENCES: dict[type, tuple[type, str]] = {
    Character: (CharacterLayer, "character_id"),
    Prop: (PropLayer, "prop_id"),
}

def _uses(layer: Layer, model: type, entry_id: str) -> bool:
    """
    Whether one layer shows a given character or prop.

    Arguments:
        layer: Layer - The layer.
        model: type - Character or Prop.
        entry_id: str - Unique ID of the entry.

    Returns:
        bool - True if the layer shows that entry.
    """
    layer_type, id_field = _LAYER_REFERENCES[model]
    return isinstance(layer, layer_type) and getattr(layer, id_field) == entry_id

def find_usage(store: StoryboardStore, project_id: str, model: type, entry_id: str) -> Usage:
    """
    Finds every scene and shot that uses a registry entry.

    A character or prop is used by every shot with a layer (anywhere in its tree) showing it; a location is used by every scene set there, and so by all of their shots.

    Arguments:
        store: StoryboardStore - Store to read from.
        project_id: str - Unique project ID.
        model: type - Character, Prop or Location.
        entry_id: str - Unique ID of the entry.

    Returns:
        Usage - Where it is used, in story order.
    """
    scenes = store.list_scenes(project_id)
    all_shots = store.list_all_shots(project_id)
    if model is Location:
        using_scene_ids = {scene.id for scene in scenes if scene.location_id == entry_id}
        using = [shot for shot in all_shots if shot.scene_id in using_scene_ids]
    else:
        using_scene_ids = set()
        using = [shot for shot in all_shots if any(_uses(layer, model, entry_id) for layer in shot.all_layers())]

    usage = Usage()
    for scene in scenes:  # Already in story order
        shots = [ShotUse(shot_id=shot.id, order=shot.order) for shot in using if shot.scene_id == scene.id]
        if shots or scene.id in using_scene_ids:  # A location's scene counts even when it has no shots yet
            usage.scenes.append(SceneUse(scene_id=scene.id, name=scene.name, order=scene.order, shots=shots))
    return usage

def _without_entry(layers: list[Layer], model: type, entry_id: str) -> list[Layer]:
    """
    Copies a layer tree without any layer showing a given character or prop -- and without any group that removing them leaves empty.

    Arguments:
        layers: list[Layer] - The layers (a shot's, or a group's children).
        model: type - Character or Prop.
        entry_id: str - Unique ID of the entry.

    Returns:
        list[Layer] - The layers that remain, in the same order.
    """
    kept: list[Layer] = []
    for layer in layers:
        if _uses(layer, model, entry_id):
            continue
        if isinstance(layer, GroupLayer):
            children = _without_entry(layer.children, model, entry_id)
            if layer.children and not children:
                continue  # The group only held what's being deleted -- an empty group left behind would just be clutter
            layer = layer.model_copy(update={"children": children})
        kept.append(layer)
    return kept

def _remove_from_shot(store: StoryboardStore, project_id: str, scene_id: str, shot_id: str, model: type, entry_id: str) -> None:
    """
    Removes a character's or prop's layers from one shot, saving it with the usual version check.

    If someone else saves the shot in between, it is reloaded and the removal applied again to their version, rather than overwriting their changes.

    Arguments:
        store: StoryboardStore - Store to read from and write to.
        project_id: str - Unique project ID.
        scene_id: str - Unique ID of the shot's scene.
        shot_id: str - Unique ID of the shot.
        model: type - Character or Prop.
        entry_id: str - Unique ID of the entry.
    """
    for attempt in range(SAVE_ATTEMPTS):
        shot = store.get_shot(project_id, scene_id, shot_id)
        layers = _without_entry(shot.layers, model, entry_id)
        if layers == shot.layers:
            return  # Nothing (left) to remove
        try:
            store.save_shot(project_id, shot.model_copy(update={"layers": layers}))
            return
        except ShotConflictError:
            if attempt == SAVE_ATTEMPTS - 1:
                raise

def delete_entry_and_uses(store: StoryboardStore, project_id: str, model: type, entry_id: str) -> Usage:
    """
    Deletes a character or prop, and every layer showing it.

    The layers go first and the entry last, so a failure part-way through never leaves a layer pointing at an entry that no longer exists.

    Raises a KeyError if there is no such entry, or a ValueError for a location (see delete_location).

    Arguments:
        store: StoryboardStore - Store to read from and write to.
        project_id: str - Unique project ID.
        model: type - Character or Prop.
        entry_id: str - Unique ID of the entry.

    Returns:
        Usage - Where it was used, now removed.
    """
    if model not in _LAYER_REFERENCES:
        raise ValueError(f"{model.__name__}s are deleted with delete_location, which decides what happens to their scenes")
    store.get_entry(project_id, model, entry_id)  # Raises a KeyError if there's no such entry
    usage = find_usage(store, project_id, model, entry_id)
    for scene in usage.scenes:
        for shot in scene.shots:
            _remove_from_shot(store, project_id, scene.scene_id, shot.shot_id, model, entry_id)
    store.delete_entry(project_id, model, entry_id)
    return usage

def delete_location(store: StoryboardStore, project_id: str, location_id: str, *, move_scenes_to: str | None) -> Usage:
    """
    Deletes a location, after either moving every scene set there to another location, or deleting those scenes (and their shots).

    The choice is required (there is no default), so nothing is ever deleted because a caller forgot to say. Moved scenes keep their shots; their backgrounds then need regenerating, as each records the location it was generated from.

    Raises a KeyError if there is no such location, or a ValueError if the scenes can't be moved where asked.

    Arguments:
        store: StoryboardStore - Store to read from and write to.
        project_id: str - Unique project ID.
        location_id: str - Unique ID of the location to delete.
        move_scenes_to: str - Location to move its scenes to, or None to delete them.

    Returns:
        Usage - The scenes that were moved or deleted.
    """
    store.get_entry(project_id, Location, location_id)  # Raises a KeyError if there's no such location
    if move_scenes_to is not None:
        if move_scenes_to == location_id:
            raise ValueError("Scenes can't be moved to the location being deleted")
        try:
            store.get_entry(project_id, Location, move_scenes_to)
        except KeyError:
            raise ValueError(f"There's no location {move_scenes_to!r} to move the scenes to") from None

    usage = find_usage(store, project_id, Location, location_id)
    for scene_use in usage.scenes:
        if move_scenes_to is None:
            store.delete_scene(project_id, scene_use.scene_id)
        else:
            scene = store.get_scene(project_id, scene_use.scene_id)
            store.save_scene(project_id, scene.model_copy(update={"location_id": move_scenes_to}))
    store.delete_entry(project_id, Location, location_id)
    return usage