"""
Generates the images a v0.2.0 project's layers show: location plates and backgrounds, character references and poses, and prop references.

Every image is stored under a key made from everything it was generated from (see storage.storyboard_store.generated_key), so nothing is ever paid for twice: asking for an image that already exists just returns its key. A location's plates and a character's or prop's references are also recorded on their registry entry, where the user can see them (and, later, replace one with a sketch -- which is then used as it is).

Backgrounds are built as a chain, one change per generation, so a place never drifts from shot to shot:

    plate (the facing) -> framing (shot size and angle) -> details -> lighting (time of day and atmosphere)

Each plate is drawn from what's on its side of the place (the location's view for that facing) -- north from that alone, every other facing with the north plate too, for what the place is made of. A facing with no view shows the north plate, as nothing says what's there. A wide, eye-level shot is the plate itself, and a close-up uses the wide background (the canvas scales it up). Each later link is skipped when it would change nothing.

Characters are drawn from a reference per orientation: the front one from their description, the others from the front one. A pose is drawn from the reference for its orientation; with no action, the layer shows the reference itself. A prop layer always shows its reference. References are kept in colour (which conditions later generations better); every image a layer shows is monochrome, and trimmed to the figure at a standard size (see cutouts).

Attributes:
    GenerateImage: Callable[...,bytes] - An image generation function: a prompt, and optionally reference_images, to image bytes (from together_caller, or faked in tests).
    RemoveBackground: Callable[[bytes],bytes] - A background removal function (from background_removal, or faked in tests).
    LAYER_IMAGE_VERSION: int - How poses are made (part of their keys): bumped whenever that changes, so old ones are made again.
"""
from typing import Callable, Protocol

from taleboard.generation import prompts
from taleboard.generation import background_removal, together_caller
from taleboard.generation.cutouts import fit_character, fit_prop, generate_cutout, remove_white_background, to_monochrome
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GeneratedLayer, PropLayer
from taleboard.schema.storyboard import Character, Location, Prop, Reference, Scene, Shot
from taleboard.storage.storyboard_store import generated_key

GenerateImage = Callable[..., bytes]
RemoveBackground = Callable[[bytes], bytes]

LAYER_IMAGE_VERSION = 2  # 2: trimmed to the figure and fitted to a standard size


class GenerationStore(Protocol):
    """
    Where generated images go -- a StoryboardStore, or an in-memory fake in tests.
    """
    def get_image(self, s3_key: str) -> bytes | None: ...
    def put_image(self, s3_key: str, image: bytes) -> None: ...
    def save_entry_image(self, project_id: str, entry: Character | Prop | Location, slot: str) -> None: ...


class Generator:
    """
    Generates (or finds) the images for one project.

    Attributes:
        project_id: str - The project's ID.
        _store: GenerationStore - Where images are read and written.
        _generate_character: GenerateImage - Draws a character (a tall, portrait image).
        _generate_background: GenerateImage - Draws a background (a square image).
        _generate_prop: GenerateImage - Draws a prop (a square image).
        _remove_background: RemoveBackground - Cuts a character out of its white background.
        _remove_prop_background: RemoveBackground - Cuts a prop out of its white background.
    """
    def __init__(
        self,
        project_id: str,
        store: GenerationStore,
        generate_character: GenerateImage = together_caller.generate_character_image,
        generate_background: GenerateImage = together_caller.generate_background_image,
        generate_prop: GenerateImage = together_caller.generate_background_image,
        remove_background: RemoveBackground = background_removal.remove_background,
        remove_prop_background: RemoveBackground = remove_white_background,
    ):
        """
        Arguments:
            project_id: str - The project's ID.
            store: GenerationStore - Where images are read and written.
            generate_character: GenerateImage - Draws a character. Defaults to Together AI's portrait generation.
            generate_background: GenerateImage - Draws a background. Defaults to Together AI's square generation.
            generate_prop: GenerateImage - Draws a prop. Defaults to Together AI's square generation.
            remove_background: RemoveBackground - Cuts out a character. Defaults to the local isnet-anime model.
            remove_prop_background: RemoveBackground - Cuts out a prop. Defaults to flood-filling its white background (the model leaves lone objects see-through).
        """
        self.project_id = project_id
        self._store = store
        self._generate_character = generate_character
        self._generate_background = generate_background
        self._generate_prop = generate_prop
        self._remove_background = remove_background
        self._remove_prop_background = remove_prop_background

    # --- Layers -------------------------------------------------------------------------------------------------

    def generate_layer(
        self,
        layer: GeneratedLayer,
        shot: Shot,
        scene: Scene,
        location: Location,
        characters: dict[str, Character],
        props: dict[str, Prop],
    ) -> GeneratedLayer:
        """
        Generates (or finds) a layer's image, as its current values say it should look.

        Raises a CutoutRejectedError if a character or prop came out empty or see-through, even after a second try.

        Arguments:
            layer: GeneratedLayer - A background, character or prop layer.
            shot: Shot - The shot it is in.
            scene: Scene - The shot's scene.
            location: Location - The scene's location.
            characters: dict[str,Character] - The project's characters, by ID.
            props: dict[str,Prop] - The project's props, by ID.

        Returns:
            GeneratedLayer - A copy of the layer showing the image, with last_generated_params recording what it was drawn from.
        """
        if isinstance(layer, BackgroundLayer):
            image = self.background(location, layer.facing, shot.shot_size, shot.angle, shot.details, scene.time_of_day, scene.atmosphere)
        elif isinstance(layer, CharacterLayer):
            image = self.character(characters[layer.character_id], layer.orientation, layer.action)
        elif isinstance(layer, PropLayer):
            image = self.prop(props[layer.prop_id], layer.orientation)
        else:
            raise TypeError(f"{type(layer).__name__} is not a generated layer")
        params = layer.current_params(shot.generation_context(scene))
        return layer.model_copy(update={"image": image, "last_generated_params": params})

    # --- Backgrounds ----------------------------------------------------------------------------------------------

    def plate(self, location: Location, facing: Facing) -> str:
        """
        A location's plate for one facing -- the one on its registry entry, or else a new one, recorded there. A facing other than north with no view is the north plate.

        Arguments:
            location: Location - The location.
            facing: Facing - Which way the camera faces.

        Returns:
            str - S3 key of the plate.
        """
        if facing in location.plates:
            return location.plates[facing]
        if facing != Facing.NORTH and facing not in location.views:
            # Nothing says what's on this side, so it shows the north plate -- not recorded as its own, so adding a view draws it
            return self.plate(location, Facing.NORTH)
        sources = [] if facing == Facing.NORTH else [self.plate(location, Facing.NORTH)]
        key = self._background("plate", prompts.plate_prompt(location, facing), sources)
        location.plates[facing] = key
        self._store.save_entry_image(self.project_id, location, facing.value)
        return key

    def background(
        self,
        location: Location,
        facing: Facing,
        shot_size: ShotSize,
        angle: CameraAngle,
        details: str,
        time_of_day: TimeOfDay,
        atmosphere: Atmosphere,
    ) -> str:
        """
        A shot's background: the plate, re-framed, with the shot's details, in the scene's light -- each link generated only if it isn't already.

        Arguments:
            location: Location - The scene's location.
            facing: Facing - Which way the camera faces.
            shot_size: ShotSize - The shot's size (a close-up gets the wide background).
            angle: CameraAngle - The shot's camera angle.
            details: str - Small visible changes to the location in this shot ("" for none).
            time_of_day: TimeOfDay - The scene's time of day.
            atmosphere: Atmosphere - The scene's weather.

        Returns:
            str - S3 key of the background.
        """
        key = self.plate(location, facing)
        framing = ShotSize.WIDE if shot_size == ShotSize.CLOSE_UP else shot_size
        if (framing, angle) != (ShotSize.WIDE, CameraAngle.EYE_LEVEL):
            key = self._background("framing", prompts.framing_prompt(location, framing, angle), [key])
        if details.strip():
            key = self._background("details", prompts.detail_prompt(location, details.strip()), [key])
        lighting = prompts.lighting_prompt(location.setting, time_of_day, atmosphere)
        if lighting is not None:
            key = self._background("lighting", lighting, [key])
        return key

    def _background(self, kind: str, prompt: str, sources: list[str]) -> str:
        """
        One link of a background chain: drawn from the prompt, with the image before it (if any) as image 1, in monochrome.
        """
        return self._derive(
            kind, prompt, sources,
            lambda images: to_monochrome(self._generate_background(prompt, **_references(images))),
        )

    # --- Characters and props ------------------------------------------------------------------------------------

    def character_reference(self, character: Character, orientation: Orientation) -> str:
        """
        A character's reference in one orientation -- the one on their registry entry, or else a new one, recorded there.

        Arguments:
            character: Character - The character.
            orientation: Orientation - Which way they face.

        Returns:
            str - S3 key of the reference.
        """
        return self._reference(
            character, orientation,
            lambda: prompts.character_prompt(character, orientation),
            lambda: self.character_reference(character, Orientation.TOWARDS_CAMERA),
            self._generate_character,
            self._remove_background,
        )

    def character(self, character: Character, orientation: Orientation, action: str) -> str:
        """
        A character layer's image: a pose drawn from their reference for the orientation, or (with no action) that reference itself.

        Arguments:
            character: Character - The character.
            orientation: Orientation - Which way they face.
            action: str - What their body is doing ("" for none).

        Returns:
            str - S3 key of the image (monochrome).
        """
        reference = self.character_reference(character, orientation)
        if not action.strip():
            return self._layer_copy(reference, fit_character)
        prompt = prompts.character_prompt(character, orientation, action.strip())
        return self._derive(
            "pose", prompt, [reference],
            lambda images: fit_character(to_monochrome(self._cutout(prompt, self._generate_character, self._remove_background, images))),
            version=LAYER_IMAGE_VERSION,
        )

    def prop_reference(self, prop: Prop, orientation: Orientation) -> str:
        """
        A prop's reference in one orientation -- the one on its registry entry, or else a new one, recorded there.

        Arguments:
            prop: Prop - The prop.
            orientation: Orientation - Which side of it faces the camera.

        Returns:
            str - S3 key of the reference.
        """
        return self._reference(
            prop, orientation,
            lambda: prompts.prop_prompt(prop, orientation),
            lambda: self.prop_reference(prop, Orientation.TOWARDS_CAMERA),
            self._generate_prop,
            self._remove_prop_background,
        )

    def prop(self, prop: Prop, orientation: Orientation) -> str:
        """
        A prop layer's image: its reference for the orientation, in monochrome.

        Arguments:
            prop: Prop - The prop.
            orientation: Orientation - Which side of it faces the camera.

        Returns:
            str - S3 key of the image (monochrome).
        """
        return self._layer_copy(self.prop_reference(prop, orientation), fit_prop)

    def _reference(
        self,
        entry: Character | Prop,
        orientation: Orientation,
        prompt: Callable[[], str],
        front: Callable[[], str],
        generate: GenerateImage,
        remove: RemoveBackground,
    ) -> str:
        """
        A character's or prop's reference in one orientation: the one recorded on its entry, or else a new cutout -- the front one drawn from the prompt alone, any other drawn from the front one -- recorded there.
        """
        if orientation in entry.references:
            return entry.references[orientation].image
        text = prompt()
        sources = [] if orientation == Orientation.TOWARDS_CAMERA else [front()]
        key = self._derive("reference", text, sources, lambda images: self._cutout(text, generate, remove, images))
        entry.references[orientation] = Reference(image=key, source="generated")
        self._store.save_entry_image(self.project_id, entry, orientation.value)
        return key

    def _cutout(self, prompt: str, generate: GenerateImage, remove: RemoveBackground, references: list[bytes]) -> bytes:
        """
        A subject drawn on white and cut out (by `remove`), regenerated once if it comes out empty or see-through.
        """
        return generate_cutout(prompt, "", generate, remove, reference_images=references or None)

    # --- Storage ------------------------------------------------------------------------------------------------

    def _layer_copy(self, source: str, fit: Callable[[bytes], bytes]) -> str:
        """
        A reference made into a layer's image -- monochrome, trimmed and fitted -- once, and never paid for.
        """
        return self._derive("monochrome", fit.__name__, [source], lambda images: fit(to_monochrome(images[0])))

    def _derive(self, kind: str, prompt: str, sources: list[str], make: Callable[[list[bytes]], bytes], version: int | None = None) -> str:
        """
        The image made from this prompt and these source images: found by its key if it already exists, or else made and stored there.

        Arguments:
            kind: str - What sort of image it is (part of its key).
            prompt: str - The prompt it is drawn from ("" if none).
            sources: list[str] - S3 keys of the images it is drawn from, in order.
            make: Callable[[list[bytes]],bytes] - Makes it, given the source images.
            version: int - How it's made, if that has changed since images of this kind were first stored -- part of its key, so an image made the old way is never reused. Defaults to None (the first way).

        Returns:
            str - S3 key of the image.
        """
        inputs = {"prompt": prompt, "sources": sources, **({"version": version} if version else {})}
        key = generated_key(self.project_id, kind, inputs)
        if self._store.get_image(key) is None:
            images = []
            for source in sources:
                image = self._store.get_image(source)
                if image is None:
                    raise LookupError(f"Source image {source!r} is missing")
                images.append(image)
            self._store.put_image(key, make(images))
        return key


def _references(images: list[bytes]) -> dict:
    """
    The reference_images argument for a generation call -- left out entirely when there are none.
    """
    return {"reference_images": images} if images else {}