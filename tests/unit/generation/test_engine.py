"""
Unit tests for the generation engine.

Covers the background chain (which links are generated, from what, and that each is only generated once), character and prop references and poses, what is recorded on registry entries, and generating a layer. Image generation and background removal are faked, and images are kept in memory, so nothing here costs anything.
"""
import io

import pytest
from PIL import Image

from taleboard.generation import prompts
from taleboard.generation.engine import Generator
from taleboard.generation.cutouts import CHARACTER_HEIGHT, PROP_SIZE, CutoutRejectedError
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Prop, Reference, Scene, Shot
from taleboard.storage.storyboard_store import generated_key

PID = "p1"


def _png(colour: tuple, mode: str = "RGB") -> bytes:
    """
    A small solid image, as PNG bytes.

    Arguments:
        colour: tuple - Its colour.
        mode: str - PIL image mode. Defaults to "RGB".

    Returns:
        bytes - The PNG.
    """
    buffer = io.BytesIO()
    Image.new(mode, (8, 8), colour).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeStore:
    """
    Keeps images in a dict, and records which entry images were saved.
    """
    def __init__(self):
        self.images: dict[str, bytes] = {}
        self.saved: list[tuple[str, str, str]] = []

    def get_image(self, s3_key: str) -> bytes | None:
        return self.images.get(s3_key)

    def put_image(self, s3_key: str, image: bytes) -> None:
        self.images[s3_key] = image

    def save_entry_image(self, project_id: str, entry, slot: str) -> None:
        self.saved.append((project_id, entry.id, slot))


class FakeGenerate:
    """
    An image generation function that records each call (prompt, and how many reference images) and returns a coloured image.
    """
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def __call__(self, text: str, negative_text: str | None = None, reference_images: list[bytes] | None = None) -> bytes:
        self.calls.append((text, len(reference_images or [])))
        return _png((200, 40, 40))


def _cut_out(image: bytes) -> bytes:
    """
    A fake background removal: a solid, fully opaque cutout of the same colour.
    """
    return _png((200, 40, 40, 255), "RGBA")


@pytest.fixture
def setup():
    """
    A generator with fake image functions, its store, and the generation fakes by name.

    Returns:
        tuple[Generator,FakeStore,dict[str,FakeGenerate]] - The generator, its store and its fakes.
    """
    store = FakeStore()
    fakes = {"character": FakeGenerate(), "background": FakeGenerate(), "prop": FakeGenerate()}
    generator = Generator(
        PID, store,
        generate_character=fakes["character"], generate_background=fakes["background"], generate_prop=fakes["prop"],
        remove_background=_cut_out,
    )
    return generator, store, fakes


def _location(**changes) -> Location:
    return Location(**{"id": "lighthouse", "name": "Lighthouse", "description": "the lamp room of a lighthouse", **changes})


def _with_views() -> Location:
    """
    The lighthouse, with what's on its north and south sides (and nothing said about east or west).
    """
    return _location(views={Facing.NORTH: "the great lens on its pedestal", Facing.SOUTH: "the top of the spiral staircase"})


def _character() -> Character:
    return Character(id="mara", name="Mara", description="a lighthouse keeper in an oilskin coat")


def _prop() -> Prop:
    return Prop(id="lamp", name="Lamp", description="a brass storm lantern")


def _is_monochrome(image: bytes) -> bool:
    """
    True if every pixel of the image is grey.
    """
    colours = Image.open(io.BytesIO(image)).convert("RGB").getcolors(maxcolors=1 << 24)
    return all(r == g == b for _, (r, g, b) in colours)


def _background(generator, location, facing=Facing.NORTH, size=ShotSize.WIDE, angle=CameraAngle.EYE_LEVEL, details="", time=TimeOfDay.DAY, weather=Atmosphere.CLEAR):
    return generator.background(location, facing, size, angle, details, time, weather)


# --- Backgrounds ---------------------------------------------------------------------------------------------------

def test_a_wide_eye_level_shot_by_day_is_the_north_plate_itself(setup):
    """
    Verifies that the plainest background is just the plate -- one generation, from the description alone, recorded on the location.
    """
    generator, store, fakes = setup
    location = _location()

    key = _background(generator, location)

    assert fakes["background"].calls == [(prompts.plate_prompt(location, Facing.NORTH), 0)]
    assert location.plates == {Facing.NORTH: Reference(image=key, source="generated")}
    assert store.saved == [(PID, "lighthouse", "north")]
    assert _is_monochrome(store.images[key])


def test_every_other_facing_is_drawn_from_the_north_plate(setup):
    """
    Verifies that a south plate first makes the north one, then is drawn from its own view with the north plate as image 1 -- and both are recorded.
    """
    generator, store, fakes = setup
    location = _with_views()

    _background(generator, location, facing=Facing.SOUTH)

    assert fakes["background"].calls == [
        (prompts.plate_prompt(location, Facing.NORTH), 0),
        (prompts.plate_prompt(location, Facing.SOUTH), 1),
    ]
    assert set(location.plates) == {Facing.NORTH, Facing.SOUTH}


def test_a_side_with_no_view_shows_the_north_plate_without_generating_it(setup):
    """
    Verifies that a facing nothing has been said about is the north plate -- at no cost, and not recorded as its own, so adding a view later draws it.
    """
    generator, store, fakes = setup
    location = _with_views()
    north = _background(generator, location)

    assert _background(generator, location, facing=Facing.EAST) == north
    assert len(fakes["background"].calls) == 1
    assert set(location.plates) == {Facing.NORTH}

    location.views[Facing.EAST] = "a window looking out to sea"
    assert _background(generator, location, facing=Facing.EAST) != north
    assert fakes["background"].calls[-1] == (prompts.plate_prompt(location, Facing.EAST), 1)


def test_an_exterior_is_lit_with_its_weather_and_an_interior_with_light_only(setup):
    """
    Verifies that the lighting edit follows the location's setting.
    """
    generator, store, fakes = setup
    inside, outside = _location(), _location(id="quay", setting=Setting.EXT)

    _background(generator, inside, time=TimeOfDay.NIGHT, weather=Atmosphere.RAINY)
    _background(generator, outside, time=TimeOfDay.NIGHT, weather=Atmosphere.RAINY)

    lighting = [text for text, _ in fakes["background"].calls if "changed only in its light" in text]
    assert lighting == [
        prompts.lighting_prompt(Setting.INT, TimeOfDay.NIGHT, Atmosphere.RAINY),
        prompts.lighting_prompt(Setting.EXT, TimeOfDay.NIGHT, Atmosphere.RAINY),
    ]


def test_a_full_chain_changes_one_thing_per_generation(setup):
    """
    Verifies that a medium, low-angle shot with details, at night in the rain, is four generations, each from the one before.
    """
    generator, store, fakes = setup
    location = _location()

    key = _background(generator, location, size=ShotSize.MEDIUM, angle=CameraAngle.LOW, details=" the lamp lit ", time=TimeOfDay.NIGHT, weather=Atmosphere.RAINY)

    assert fakes["background"].calls == [
        (prompts.plate_prompt(location, Facing.NORTH), 0),
        (prompts.framing_prompt(location, ShotSize.MEDIUM, CameraAngle.LOW), 1),
        (prompts.detail_prompt(location, "the lamp lit"), 1),
        (prompts.lighting_prompt(Setting.INT, TimeOfDay.NIGHT, Atmosphere.RAINY), 1),
    ]
    assert "/generated/lighting/" in key


def test_nothing_in_a_chain_is_generated_twice(setup):
    """
    Verifies that a second shot sharing the start of a chain reuses it, and that asking again for the same background costs nothing.
    """
    generator, store, fakes = setup
    location = _location()
    first = _background(generator, location, size=ShotSize.MEDIUM, details="the lamp lit")
    calls = len(fakes["background"].calls)

    assert _background(generator, location, size=ShotSize.MEDIUM, details="the lamp lit") == first
    _background(generator, location, size=ShotSize.MEDIUM, details="the door open")

    assert len(fakes["background"].calls) == calls + 1  # Only the new details


def test_an_image_already_stored_is_found_even_if_the_entry_lost_its_record_of_it(setup):
    """
    Verifies that keys depend only on what an image was drawn from: a plate whose record was lost is found again, not paid for twice.
    """
    generator, store, fakes = setup
    key = _background(generator, _location())

    assert _background(generator, _location()) == key  # A fresh copy of the entry, with no plates recorded
    assert len(fakes["background"].calls) == 1


def test_a_close_up_uses_the_wide_background(setup):
    """
    Verifies that a close-up is never generated: it gets the same background as a wide shot of the same angle.
    """
    generator, store, fakes = setup
    location = _location()

    assert _background(generator, location, size=ShotSize.CLOSE_UP, angle=CameraAngle.HIGH) == _background(generator, location, angle=CameraAngle.HIGH)
    assert len(fakes["background"].calls) == 2  # Plate + the high-angle framing


def test_relighting_reuses_the_view_and_adds_one_generation(setup):
    """
    Verifies that the same view at another time of day costs only the lighting edit -- the reason lighting comes last.
    """
    generator, store, fakes = setup
    location = _location()
    _background(generator, location, size=ShotSize.MEDIUM, details="the lamp lit")
    calls = len(fakes["background"].calls)

    _background(generator, location, size=ShotSize.MEDIUM, details="the lamp lit", time=TimeOfDay.DUSK)

    assert fakes["background"].calls[calls:] == [(prompts.lighting_prompt(Setting.INT, TimeOfDay.DUSK, Atmosphere.CLEAR), 1)]


def test_a_sketched_plate_on_the_entry_is_used_as_it_is(setup):
    """
    Verifies that a plate recorded on the entry (eg:- a sketch) is used rather than generated, and the chain is drawn from it.
    """
    generator, store, fakes = setup
    location = _location()
    store.images["sketch.png"] = _png((255, 255, 255))
    location.plates[Facing.NORTH] = Reference(image="sketch.png", source="sketch")

    assert _background(generator, location) == "sketch.png"
    _background(generator, location, size=ShotSize.MEDIUM)
    assert fakes["background"].calls == [(prompts.framing_prompt(location, ShotSize.MEDIUM, CameraAngle.EYE_LEVEL), 1)]


# --- Characters and props -----------------------------------------------------------------------------------------

def test_a_characters_front_reference_is_drawn_from_their_description_and_kept_in_colour(setup):
    """
    Verifies that the front reference is one cutout from the prompt alone, recorded on the character, and not made monochrome.
    """
    generator, store, fakes = setup
    mara = _character()

    key = generator.character_reference(mara, Orientation.TOWARDS_CAMERA)

    assert fakes["character"].calls == [(prompts.character_prompt(mara, Orientation.TOWARDS_CAMERA), 0)]
    assert mara.references == {Orientation.TOWARDS_CAMERA: Reference(image=key, source="generated")}
    assert store.saved == [(PID, "mara", "towards_camera")]
    assert not _is_monochrome(store.images[key])


def test_a_pose_is_drawn_from_the_reference_for_its_orientation_which_is_drawn_from_the_front(setup):
    """
    Verifies the order for a first pose facing left: front reference, left reference (from the front), then the pose (from the left), monochrome.
    """
    generator, store, fakes = setup
    mara = _character()

    key = generator.character(mara, Orientation.LEFT, "one hand raised, gripping")

    assert fakes["character"].calls == [
        (prompts.character_prompt(mara, Orientation.TOWARDS_CAMERA), 0),
        (prompts.character_prompt(mara, Orientation.LEFT), 1),
        (prompts.character_prompt(mara, Orientation.LEFT, "one hand raised, gripping"), 1),
    ]
    assert set(mara.references) == {Orientation.TOWARDS_CAMERA, Orientation.LEFT}
    assert _is_monochrome(store.images[key])
    assert Image.open(io.BytesIO(store.images[key])).height == CHARACTER_HEIGHT


def test_a_character_with_no_action_shows_their_reference_for_free(setup):
    """
    Verifies that with no action the layer shows a monochrome copy of the reference, at no extra generation.
    """
    generator, store, fakes = setup
    mara = _character()

    key = generator.character(mara, Orientation.TOWARDS_CAMERA, "  ")

    assert len(fakes["character"].calls) == 1  # The reference only
    assert key != mara.references[Orientation.TOWARDS_CAMERA].image
    assert _is_monochrome(store.images[key])
    assert Image.open(io.BytesIO(store.images[key])).height == CHARACTER_HEIGHT


def test_a_pose_made_before_trimming_is_never_reused(setup):
    """
    Verifies that a pose stored under its old (unversioned) key -- untrimmed -- is drawn again rather than shown.
    """
    generator, store, fakes = setup
    mara = _character()
    reference = generator.character_reference(mara, Orientation.TOWARDS_CAMERA)
    prompt = prompts.character_prompt(mara, Orientation.TOWARDS_CAMERA, "waving")
    old = generated_key(PID, "pose", {"prompt": prompt, "sources": [reference]})
    store.images[old] = _png((0, 0, 0, 255), "RGBA")

    key = generator.character(mara, Orientation.TOWARDS_CAMERA, "waving")

    assert key != old
    assert len(fakes["character"].calls) == 2  # The reference, then the pose drawn again


def test_a_pose_is_only_generated_once(setup):
    """
    Verifies that the same character, orientation and action anywhere in the project reuse one image.
    """
    generator, store, fakes = setup
    mara = _character()

    first = generator.character(mara, Orientation.RIGHT, "waving")
    assert generator.character(mara, Orientation.RIGHT, "waving") == first
    assert len(fakes["character"].calls) == 3  # Front, right, the pose


def test_a_prop_layer_shows_its_reference_drawn_from_the_front(setup):
    """
    Verifies that a prop facing away costs its front and back references (the back drawn from the front), and its layer image is a monochrome copy.
    """
    generator, store, fakes = setup
    lamp = _prop()

    key = generator.prop(lamp, Orientation.AWAY_FROM_CAMERA)

    assert fakes["prop"].calls == [
        (prompts.prop_prompt(lamp, Orientation.TOWARDS_CAMERA), 0),
        (prompts.prop_prompt(lamp, Orientation.AWAY_FROM_CAMERA), 1),
    ]
    assert fakes["character"].calls == []
    assert _is_monochrome(store.images[key])
    assert max(Image.open(io.BytesIO(store.images[key])).size) == PROP_SIZE


def test_an_empty_cutout_is_tried_again_and_then_given_up_on(setup):
    """
    Verifies that a cutout that keeps coming out empty raises CutoutRejectedError, records nothing and stores nothing.
    """
    generator, store, fakes = setup
    generator._remove_background = lambda image: _png((0, 0, 0, 0), "RGBA")
    mara = _character()

    with pytest.raises(CutoutRejectedError):
        generator.character_reference(mara, Orientation.TOWARDS_CAMERA)
    assert len(fakes["character"].calls) == 2
    assert mara.references == {} and store.images == {} and store.saved == []


# --- Layers ------------------------------------------------------------------------------------------------------

def _shot_and_scene(**shot_fields) -> tuple[Shot, Scene]:
    scene = Scene(location_id="lighthouse", time_of_day=TimeOfDay.NIGHT)
    return Shot(scene_id=scene.id, **shot_fields), scene


@pytest.mark.parametrize("layer", [
    BackgroundLayer(facing=Facing.EAST),
    CharacterLayer(character_id="mara", orientation=Orientation.LEFT, action="waving"),
    PropLayer(prop_id="lamp", orientation=Orientation.RIGHT),
])
def test_generating_a_layer_shows_its_image_and_records_what_it_was_drawn_from(setup, layer):
    """
    Verifies that generate_layer returns a copy with its image set and nothing left to regenerate, leaving the original as it was.

    Arguments:
        layer: GeneratedLayer - A background, character or prop layer.
    """
    generator, store, fakes = setup
    shot, scene = _shot_and_scene(shot_size=ShotSize.MEDIUM, details="the lamp lit")

    done = generator.generate_layer(layer, shot, scene, _location(), {"mara": _character()}, {"lamp": _prop()})

    assert done.image in store.images and _is_monochrome(store.images[done.image])
    entry = {"background": _location(), "character": _character(), "prop": _prop()}[done.type]
    assert done.needs_regeneration(shot.generation_context(scene), entry) is False
    assert (done.id, done.transform) == (layer.id, layer.transform)
    assert layer.image is None


def test_a_background_layer_is_drawn_for_its_shot_and_scene(setup):
    """
    Verifies that a background layer's image is the chain for its facing, the shot's framing and details, and the scene's lighting.
    """
    generator, store, fakes = setup
    shot, scene = _shot_and_scene(shot_size=ShotSize.MEDIUM, details="the lamp lit")
    location = _location()

    done = generator.generate_layer(BackgroundLayer(facing=Facing.WEST), shot, scene, location, {}, {})

    assert done.image == _background(generator, location, Facing.WEST, ShotSize.MEDIUM, details="the lamp lit", time=TimeOfDay.NIGHT)


def test_only_generated_layers_can_be_generated(setup):
    """
    Verifies that asking for a text layer's image is a TypeError.
    """
    generator, store, fakes = setup
    shot, scene = _shot_and_scene()

    with pytest.raises(TypeError):
        generator.generate_layer(TextLayer(text="hi"), shot, scene, _location(), {}, {})


def test_props_are_cut_out_by_the_prop_remover_and_characters_by_the_model():
    """
    Verifies which background removal each subject gets: props their own (the white-background flood fill, by default), characters the model.
    """
    removed: list[str] = []
    generator = Generator(
        PID, FakeStore(),
        generate_character=FakeGenerate(), generate_background=FakeGenerate(), generate_prop=FakeGenerate(),
        remove_background=lambda image: removed.append("model") or _cut_out(image),
        remove_prop_background=lambda image: removed.append("prop") or _cut_out(image),
    )

    generator.prop(_prop(), Orientation.TOWARDS_CAMERA)
    generator.character(_character(), Orientation.TOWARDS_CAMERA, "")

    assert removed == ["prop", "model"]


def test_a_recorded_reference_is_drawn_again_once_its_description_changes(setup):
    """
    Verifies that a generated reference on the entry is only a record: the same description finds it again for free, an edited one draws (and records) a new one.
    """
    generator, store, fakes = setup
    mara = _character()
    first = generator.character_reference(mara, Orientation.TOWARDS_CAMERA)

    assert generator.character_reference(mara, Orientation.TOWARDS_CAMERA) == first
    assert len(fakes["character"].calls) == 1
    edited = mara.model_copy(update={"description": "a lighthouse keeper in a red scarf"})
    second = generator.character_reference(edited, Orientation.TOWARDS_CAMERA)

    assert second != first and len(fakes["character"].calls) == 2
    assert edited.references[Orientation.TOWARDS_CAMERA].image == second
    assert store.saved[-1] == (PID, "mara", "towards_camera")


def test_a_recorded_plate_is_drawn_again_once_its_view_changes(setup):
    """
    Verifies the same for plates: an edited view draws a new plate, and the entry records it.
    """
    generator, store, fakes = setup
    office = _with_views()
    first = generator.plate(office, Facing.NORTH)
    edited = office.model_copy(update={"views": {**office.views, Facing.NORTH: "a bare brick wall"}})

    second = generator.plate(edited, Facing.NORTH)

    assert second != first and edited.plates[Facing.NORTH].image == second
    assert len(fakes["background"].calls) == 2


def test_a_sketched_reference_is_cut_out_once_and_drawn_from(setup):
    """
    Verifies that a character's sketch is cut out of its paper (once -- then found by its key), and that a pose is drawn from the cutout, not the paper.
    """
    generator, store, fakes = setup
    removed: list[bytes] = []
    generator._remove_background = lambda image: removed.append(image) or _cut_out(image)
    mara = _character()
    store.images["sketch.png"] = _png((250, 250, 250))
    mara.references[Orientation.TOWARDS_CAMERA] = Reference(image="sketch.png", source="sketch")

    first = generator.character_reference(mara, Orientation.TOWARDS_CAMERA)
    assert generator.character_reference(mara, Orientation.TOWARDS_CAMERA) == first
    generator.character(mara, Orientation.TOWARDS_CAMERA, "waving")

    assert first != "sketch.png" and removed.count(store.images["sketch.png"]) == 1  # The pose's own cutout is removed too -- count only the sketch's
    assert fakes["character"].calls == [(prompts.character_prompt(mara, Orientation.TOWARDS_CAMERA, "waving"), 1)]  # Only the pose
    assert mara.references[Orientation.TOWARDS_CAMERA].image == "sketch.png"  # The entry keeps the sketch itself


def test_a_sketch_kept_with_its_background_is_used_untouched(setup):
    """
    Verifies that a sketch the user said to keep as it is goes straight to the layer, never through background removal.
    """
    generator, store, fakes = setup
    generator._remove_prop_background = lambda image: pytest.fail("a kept sketch was cut out")
    lamp = _prop()
    store.images["lamp-sketch.png"] = _png((250, 250, 250))
    lamp.references[Orientation.TOWARDS_CAMERA] = Reference(image="lamp-sketch.png", source="sketch", remove_background=False)

    assert generator.prop_reference(lamp, Orientation.TOWARDS_CAMERA) == "lamp-sketch.png"
    assert fakes["prop"].calls == []
