"""
Works out what a Generate request will draw -- which layers, in what order -- and at most how many images that takes, without drawing anything.

Kept apart from the engine so the API can use it: the engine needs the image-generation and background-removal libraries, which only the worker has.

Asking for a whole shot, scene or project draws only the layers that need it (never drawn, or changed since); asking for one layer always draws it.
"""
from dataclasses import dataclass

from taleboard.generation.prompts import lighting_prompt
from taleboard.schema.enums import CameraAngle, Facing, Orientation, ShotSize
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GeneratedLayer, PropLayer
from taleboard.schema.storyboard import Character, Location, Prop, Scene, Shot


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


def needs_drawing(layer: GeneratedLayer, shot: Shot, scene: Scene) -> bool:
    """
    True if a layer has never been drawn, or what it depends on has changed since it was.

    Arguments:
        layer: GeneratedLayer - The layer.
        shot: Shot - The shot it is in.
        scene: Scene - The shot's scene.

    Returns:
        bool - Whether it needs drawing.
    """
    return layer.image is None or layer.needs_regeneration(shot.generation_context(scene))


def layers_to_draw(shots: list[tuple[Scene, Shot]]) -> list[Planned]:
    """
    Every layer in these shots that needs drawing, in story order: shot by shot, and bottom to top within each (so a shot's background comes first).

    Arguments:
        shots: list[tuple[Scene,Shot]] - The shots, in order, each with its scene.

    Returns:
        list[Planned] - The layers to draw.
    """
    return [
        Planned(scene, shot, layer)
        for scene, shot in shots
        for layer in shot.all_layers()
        if isinstance(layer, GeneratedLayer) and needs_drawing(layer, shot, scene)
    ]


def images_at_most(
    planned: list[Planned],
    locations: dict[str, Location],
    characters: dict[str, Character],
    props: dict[str, Prop],
) -> int:
    """
    The most images drawing these layers can take: each link of each background chain, and each reference and pose, counted once however many layers share it.

    An upper bound, as it never checks for images already drawn (a pose, or a chain link, another shot already paid for) -- only for plates and references recorded on their registry entries.

    Arguments:
        planned: list[Planned] - The layers to draw.
        locations: dict[str,Location] - The project's locations, by ID.
        characters: dict[str,Character] - The project's characters, by ID.
        props: dict[str,Prop] - The project's props, by ID.

    Returns:
        int - The most images it will take.
    """
    images: set[tuple] = set()
    for item in planned:
        layer, shot, scene = item.layer, item.shot, item.scene
        if isinstance(layer, BackgroundLayer):
            location = locations.get(scene.location_id)
            if location is not None:
                images |= _background_images(location, layer.facing, shot, scene)
        elif isinstance(layer, CharacterLayer):
            character = characters.get(layer.character_id)
            if character is not None:
                images |= _reference_images("character", character, layer.orientation)
                if layer.action.strip():
                    images.add(("pose", character.id, layer.orientation, layer.action.strip()))
        elif isinstance(layer, PropLayer):
            prop = props.get(layer.prop_id)
            if prop is not None:
                images |= _reference_images("prop", prop, layer.orientation)
    return len(images)


def _background_images(location: Location, facing: Facing, shot: Shot, scene: Scene) -> set[tuple]:
    """
    The images one background's chain can take, each named by everything that makes it a different image (as the engine's keys are).
    """
    images: set[tuple] = set()
    if facing != Facing.NORTH and facing not in location.views:
        facing = Facing.NORTH  # Nothing says what's on that side, so it shows the north plate
    for plate in {Facing.NORTH, facing}:
        if plate not in location.plates:
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


def _reference_images(kind: str, entry: Character | Prop, orientation: Orientation) -> set[tuple]:
    """
    The references a character or prop facing this way can take: the front one, and the one for this orientation (drawn from the front).
    """
    return {
        (kind, entry.id, wanted)
        for wanted in {Orientation.TOWARDS_CAMERA, orientation}
        if wanted not in entry.references
    }