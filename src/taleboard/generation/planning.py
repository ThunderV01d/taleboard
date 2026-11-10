"""
Works out what a Generate request will draw -- which layers, in what order -- and at most how many images that takes, without drawing anything.

Kept apart from the engine so the API can use it: the engine needs the image-generation and background-removal libraries, which only the worker has.

Asking for a whole shot, scene or project draws only the layers that need it (never drawn, or changed since -- in the layer, its shot, its scene or its registry entry); asking for one layer always draws it.
"""
from dataclasses import dataclass

from taleboard.generation.prompts import lighting_prompt
from taleboard.schema.enums import CameraAngle, Facing, Orientation, ShotSize
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GeneratedLayer, PropLayer
from taleboard.schema.storyboard import Character, Location, Prop, Scene, Shot

# The params a layer records from its registry entry, rather than from itself, its shot or its scene
_UPSTREAM = {"location_description", "setting", "view", "north_view", "description", "sketches"}


@dataclass(frozen=True)
class Planned:
    """
    One layer a request will draw, with where it is.

    Attributes:
        scene: Scene - The scene its shot is in.
        shot: Shot - The shot it is in.
        layer: GeneratedLayer - The layer.
    """
    scene: Scene
    shot: Shot
    layer: GeneratedLayer


@dataclass(frozen=True)
class Registry:
    """
    A project's registries -- what every generated layer is drawn from, besides itself, its shot and its scene.

    Attributes:
        locations: dict[str,Location] - The project's locations, by ID.
        characters: dict[str,Character] - The project's characters, by ID.
        props: dict[str,Prop] - The project's props, by ID.
    """
    locations: dict[str, Location]
    characters: dict[str, Character]
    props: dict[str, Prop]

    @classmethod
    def load(cls, boards, project_id: str) -> "Registry":
        """
        Reads a project's registries.

        Arguments:
            boards: StoryboardStore - Store to read from.
            project_id: str - Unique project ID.

        Returns:
            Registry - The project's registries.
        """
        return cls(
            {entry.id: entry for entry in boards.list_entries(project_id, Location)},
            {entry.id: entry for entry in boards.list_entries(project_id, Character)},
            {entry.id: entry for entry in boards.list_entries(project_id, Prop)},
        )

    def entry_for(self, layer: GeneratedLayer, scene: Scene) -> Character | Prop | Location | None:
        """
        The registry entry a generated layer is drawn from: its scene's location for a background, else its character or prop. None if it's gone.
        """
        if isinstance(layer, BackgroundLayer):
            return self.locations.get(scene.location_id)
        if isinstance(layer, CharacterLayer):
            return self.characters.get(layer.character_id)
        if isinstance(layer, PropLayer):
            return self.props.get(layer.prop_id)
        return None


def needs_drawing(layer: GeneratedLayer, shot: Shot, scene: Scene, registry: Registry) -> bool:
    """
    True if a layer has never been drawn, or what it depends on has changed since it was -- in the layer, its shot, its scene or its registry entry.

    Arguments:
        layer: GeneratedLayer - The layer.
        shot: Shot - The shot it is in.
        scene: Scene - The shot's scene.
        registry: Registry - The project's registries.

    Returns:
        bool - Whether it needs drawing.
    """
    return layer.changes(shot.generation_context(scene), registry.entry_for(layer,scene)) is not None


def out_of_date(shot: Shot, scene: Scene, registry: Registry) -> dict[str, list[str]]:
    """
    The shot's layers that need drawing (exactly those generation would draw), each with what's changed since it was drawn.

    Arguments:
        shot: Shot - The shot.
        scene: Scene - The shot's scene.
        registry: Registry - The project's registries.

    Returns:
        dict[str,list[str]] - What's changed (the params' names -- empty for a layer never drawn), by layer ID. Layers that are up to date are not listed.
    """
    context = shot.generation_context(scene)
    changed = {}
    for layer in shot.all_layers():
        if isinstance(layer, GeneratedLayer):
            changes = layer.changes(context, registry.entry_for(layer, scene))
            if changes is not None:
                changed[layer.id] = changes
    return changed


def layers_to_draw(shots: list[tuple[Scene, Shot]], registry: Registry) -> list[Planned]:
    """
    Every layer in these shots that needs drawing, in story order: shot by shot, and bottom to top within each (so a shot's background comes first).

    Arguments:
        shots: list[tuple[Scene,Shot]] - The shots, in order, each with its scene.
        registry: Registry - The project's registries.

    Returns:
        list[Planned] - The layers to draw.
    """
    return [
        Planned(scene, shot, layer)
        for scene, shot in shots
        for layer in shot.all_layers()
        if isinstance(layer, GeneratedLayer) and needs_drawing(layer, shot, scene, registry)
    ]


def images_at_most(planned: list[Planned], registry: Registry) -> int:
    """
    The most images drawing these layers can take: each link of each background chain, and each reference and pose, counted once however many layers share it.

    An upper bound, as it never checks for images already drawn (a pose, or a chain link, another shot already paid for). A plate or reference recorded on its registry entry is counted as free -- unless a layer drawn from it has seen its entry change since, as a generated one is then drawn again (a sketched one never is).

    Arguments:
        planned: list[Planned] - The layers to draw.
        registry: Registry - The project's registries.

    Returns:
        int - The most images it will take.
    """
    images: set[tuple] = set()
    for item in planned:
        layer, shot, scene = item.layer, item.shot, item.scene
        entry = registry.entry_for(layer, scene)
        if entry is None:
            continue  # Gone from the registry: the worker fails it without drawing anything
        redraw = _entry_changed(layer, shot, scene, entry)
        if isinstance(layer, BackgroundLayer):
            images |= _background_images(entry, layer.facing, shot, scene, redraw)
        elif isinstance(layer, CharacterLayer):
            images |= _reference_images("character", entry, layer.orientation, redraw)
            if layer.action.strip():
                images.add(("pose", entry.id, layer.orientation, layer.action.strip()))
        elif isinstance(layer, PropLayer):
            images |= _reference_images("prop", entry, layer.orientation, redraw)
    return len(images)


def _entry_changed(layer: GeneratedLayer, shot: Shot, scene: Scene, entry: Character | Prop | Location) -> bool:
    """
    Whether what a drawn layer recorded of its registry entry differs from the entry now (False for a layer never drawn).
    """
    last = layer.last_generated_params
    if last is None:
        return False
    now = layer.current_params(shot.generation_context(scene), entry)
    return last.model_dump(include=_UPSTREAM) != now.model_dump(include=_UPSTREAM)


def _background_images(location: Location, facing: Facing, shot: Shot, scene: Scene, redraw: bool) -> set[tuple]:
    """
    The images one background's chain can take, each named by everything that makes it a different image (as the engine's keys are).
    """
    images: set[tuple] = set()
    if facing != Facing.NORTH and facing not in location.views:
        facing = Facing.NORTH  # Nothing says what's on that side, so it shows the north plate
    for plate in {Facing.NORTH, facing}:
        recorded = location.plates.get(plate)
        if recorded is None or (redraw and recorded.source == "generated"):
            images.add(("plate", location.id, plate))
    chain: tuple = (location.id, facing)
    framing = ShotSize.WIDE if shot.shot_size == ShotSize.CLOSE_UP else shot.shot_size
    if (framing, shot.angle) != (ShotSize.WIDE, CameraAngle.EYE_LEVEL):
        chain += (framing, shot.angle)
        images.add(("framing",) + chain)
    if shot.details.strip():
        chain += (shot.details.strip(),)
        images.add(("details",) + chain)
    if lighting_prompt(location.setting, scene.time_of_day, scene.atmosphere) is not None:
        images.add(("lighting",) + chain + (location.setting, scene.time_of_day, scene.atmosphere))
    return images


def _reference_images(kind: str, entry: Character | Prop, orientation: Orientation, redraw: bool) -> set[tuple]:
    """
    The references a character or prop facing this way can take: the front one, and the one for this orientation (drawn from the front).
    """
    return {
        (kind, entry.id, wanted)
        for wanted in {Orientation.TOWARDS_CAMERA, orientation}
        if wanted not in entry.references or (redraw and entry.references[wanted].source == "generated")
    }