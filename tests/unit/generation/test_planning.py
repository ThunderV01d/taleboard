"""
Unit tests for planning what a Generate request draws.

Covers which layers need drawing (never drawn, or changed since -- in the layer, its shot, its scene or its registry entry) and what changed, their order, and the most images drawing them can take -- each image counted once however many layers share it.
"""
import pytest

from taleboard.generation.planning import Planned, Registry, images_at_most, layers_to_draw, needs_drawing, out_of_date
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Prop, Reference, Scene, Shot

SCENE = Scene(id="s1", location_id="office")


def _locations(**changes) -> dict[str, Location]:
    return {"office": Location(**{"id": "office", "name": "Office", "views": {Facing.NORTH: "a window", Facing.SOUTH: "a door"}, **changes})}


def _characters(**changes) -> dict[str, Character]:
    return {"mara": Character(id="mara", name="Mara", **changes)}


def _props() -> dict[str, Prop]:
    return {"lamp": Prop(id="lamp", name="Lamp")}


def _registry(**location_changes) -> Registry:
    return Registry(_locations(**location_changes), _characters(), _props())


def _drawn(layer, shot: Shot, scene: Scene = SCENE, registry: Registry | None = None):
    """
    The layer as if just generated (from the given registries, or the usual ones): an image, and the params it was drawn from.
    """
    entry = (registry or _registry()).entry_for(layer, scene)
    return layer.model_copy(update={"image": "x.png", "last_generated_params": layer.current_params(shot.generation_context(scene), entry)})


def _planned(*layers, scene: Scene = SCENE, **shot_fields) -> list[Planned]:
    shot = Shot(scene_id=scene.id, layers=list(layers), **shot_fields)
    return [Planned(scene, shot, layer) for layer in layers]


def test_a_layer_needs_drawing_if_never_drawn_or_changed_since():
    """
    Verifies needs_drawing: a new layer does, a just-drawn one doesn't, and one whose action changed since does again.
    """
    shot = Shot(scene_id="s1")
    mara = CharacterLayer(character_id="mara", action="waving")
    drawn = _drawn(mara, shot)

    assert needs_drawing(mara, shot, SCENE, _registry()) is True
    assert needs_drawing(drawn, shot, SCENE, _registry()) is False
    assert needs_drawing(drawn.model_copy(update={"action": "sitting"}), shot, SCENE, _registry()) is True


def test_out_of_date_says_what_changed_and_leaves_out_what_is_up_to_date():
    """
    Verifies out_of_date: a layer never drawn has nothing listed as changed, one drawn and untouched isn't there at all, and an edited one names each param that changed -- in the layer, its shot and its registry entry.
    """
    shot = Shot(scene_id="s1")
    background = _drawn(BackgroundLayer(id="bg"), shot)
    mara = _drawn(CharacterLayer(id="mara", character_id="mara", action="waving"), shot)
    shot.layers = [background, GroupLayer(children=[mara.model_copy(update={"action": "sitting"})]), PropLayer(id="lamp", prop_id="lamp"), TextLayer()]
    edited = Registry(_locations(), _characters(description="Tall, in a yellow raincoat"), _props())

    assert out_of_date(shot, SCENE, edited) == {"mara": ["action", "description"], "lamp": []}
    assert out_of_date(shot.model_copy(update={"shot_size": ShotSize.CLOSE_UP}), SCENE, edited)["bg"] == ["shot_size"]


def test_a_layer_changed_and_changed_back_is_up_to_date_again():
    """
    Verifies that changes compares with what the image was drawn from, so undoing an edit takes the layer off the list.
    """
    shot = Shot(scene_id="s1")
    drawn = _drawn(CharacterLayer(character_id="mara", orientation=Orientation.LEFT), shot)
    context = shot.generation_context(SCENE)
    mara = _registry().characters["mara"]

    turned = drawn.model_copy(update={"orientation": Orientation.RIGHT})
    turned_back = turned.model_copy(update={"orientation": Orientation.LEFT})

    assert turned.changes(context, mara) == ["orientation"]
    assert turned_back.changes(context, mara) is None


def test_a_layer_with_params_but_no_image_counts_as_never_drawn():
    """
    Verifies that a layer whose image has gone (but whose params are still recorded) is to be drawn, as one never drawn.
    """
    shot = Shot(scene_id="s1")
    drawn = _drawn(PropLayer(prop_id="lamp"), shot)

    assert drawn.model_copy(update={"image": None}).changes(shot.generation_context(SCENE), _registry().props["lamp"]) == []


def test_only_the_layers_that_need_it_are_drawn_in_story_order():
    """
    Verifies that layers_to_draw goes shot by shot, bottom to top (into groups too), skipping text, images and layers already up to date.
    """
    first = Shot(scene_id="s1", order=0)
    first.layers = [BackgroundLayer(id="bg1"), GroupLayer(children=[CharacterLayer(id="mara", character_id="mara"), TextLayer()])]
    second = Shot(scene_id="s1", order=1)
    second.layers = [_drawn(BackgroundLayer(id="bg2"), second), PropLayer(id="lamp", prop_id="lamp")]

    planned = layers_to_draw([(SCENE, first), (SCENE, second)], _registry())

    assert [p.layer.id for p in planned] == ["bg1", "mara", "lamp"]
    assert [p.shot.id for p in planned] == [first.id, first.id, second.id]


def test_a_plain_background_is_at_most_one_image_its_plate():
    """
    Verifies the cheapest background: a wide, eye-level shot by day, with no details, is just its plate.
    """
    assert images_at_most(_planned(BackgroundLayer(), shot_size=ShotSize.WIDE), Registry(_locations(), {}, {})) == 1


def test_every_link_of_a_background_chain_counts():
    """
    Verifies that a south, medium, low-angle shot with details, at night, counts north and south plates, framing, details and lighting.
    """
    night = Scene(id="s2", location_id="office", time_of_day=TimeOfDay.NIGHT)
    planned = _planned(BackgroundLayer(facing=Facing.SOUTH), scene=night, shot_size=ShotSize.MEDIUM, angle=CameraAngle.LOW, details="the lamp lit")

    assert images_at_most(planned, Registry(_locations(), {}, {})) == 5


def test_plates_already_on_the_entry_are_not_counted():
    """
    Verifies that recorded plates cost nothing -- including the north one a south plate is drawn from.
    """
    locations = _locations(plates={Facing.NORTH: "n.png", Facing.SOUTH: "s.png"})

    assert images_at_most(_planned(BackgroundLayer(facing=Facing.SOUTH), shot_size=ShotSize.WIDE), Registry(locations, {}, {})) == 0


def test_a_side_with_no_view_counts_as_the_north_plate():
    """
    Verifies that facing a side nothing has been said about counts only the north plate, as that's what it shows.
    """
    assert images_at_most(_planned(BackgroundLayer(facing=Facing.EAST), shot_size=ShotSize.WIDE), Registry(_locations(), {}, {})) == 1


def test_a_close_up_counts_as_its_wide_background():
    """
    Verifies that a close-up costs what a wide shot of the same angle does -- it uses the wide background.
    """
    close_up = _planned(BackgroundLayer(), shot_size=ShotSize.CLOSE_UP, angle=CameraAngle.HIGH)
    wide = _planned(BackgroundLayer(), shot_size=ShotSize.WIDE, angle=CameraAngle.HIGH)

    assert images_at_most(close_up, Registry(_locations(), {}, {})) == images_at_most(wide, Registry(_locations(), {}, {})) == 2


def test_images_shared_by_many_layers_count_once():
    """
    Verifies that two shots with the same background, and two layers with the same pose, count each image once.
    """
    planned = (
        _planned(BackgroundLayer(), CharacterLayer(character_id="mara", action="waving"), shot_size=ShotSize.MEDIUM)
        + _planned(BackgroundLayer(), CharacterLayer(character_id="mara", action="waving"), shot_size=ShotSize.MEDIUM)
    )

    # Plate + medium framing, Mara's front reference + her pose
    assert images_at_most(planned, Registry(_locations(), _characters(), {})) == 4


@pytest.mark.parametrize("orientation, action, references, expected", [
    (Orientation.TOWARDS_CAMERA, "", {}, 1),  # The front reference is the layer's image
    (Orientation.LEFT, "", {}, 2),  # Front, then left from it
    (Orientation.LEFT, "waving", {}, 3),  # ...then the pose
    (Orientation.LEFT, "waving", {Orientation.TOWARDS_CAMERA: Reference(image="f.png", source="generated")}, 2),
    (Orientation.LEFT, "", {o: Reference(image="r.png", source="sketch") for o in (Orientation.TOWARDS_CAMERA, Orientation.LEFT)}, 0),
])
def test_a_character_counts_the_references_it_still_needs_and_its_pose(orientation, action, references, expected):
    """
    Verifies a character's count: the front and own-orientation references not yet recorded, plus a pose if it has an action.

    Arguments:
        orientation: Orientation - Which way the layer faces.
        action: str - Its action.
        references: dict - References already on the character's entry.
        expected: int - The most images it takes.
    """
    planned = _planned(CharacterLayer(character_id="mara", orientation=orientation, action=action))

    assert images_at_most(planned, Registry({}, _characters(references=references), {})) == expected


def test_a_prop_is_only_ever_its_references():
    """
    Verifies that a prop facing away counts its front and back references, and nothing else.
    """
    assert images_at_most(_planned(PropLayer(prop_id="lamp", orientation=Orientation.AWAY_FROM_CAMERA)), Registry({}, {}, _props())) == 2


def test_an_exterior_in_the_rain_counts_its_lighting_and_daylight_does_not():
    """
    Verifies that lighting counts only when there is something to light -- for an exterior as for an interior.
    """
    rainy = Scene(id="s3", location_id="office", atmosphere=Atmosphere.RAINY)
    exterior = _locations(setting=Setting.EXT)

    assert images_at_most(_planned(BackgroundLayer(), scene=rainy, shot_size=ShotSize.WIDE), Registry(exterior, {}, {})) == 2
    assert images_at_most(_planned(BackgroundLayer(), shot_size=ShotSize.WIDE), Registry(exterior, {}, {})) == 1


def test_a_registry_edit_marks_the_layers_drawn_from_that_entry():
    """
    Verifies that a character's description, and a sketch replacing their front reference, each mark a layer drawn of them -- and that another character's edit doesn't.
    """
    shot = Shot(scene_id="s1")
    drawn = _drawn(CharacterLayer(character_id="mara", orientation=Orientation.LEFT), shot)
    edited = Registry(_locations(), _characters(description="a keeper in a red scarf"), _props())
    sketched = Registry(_locations(), _characters(references={Orientation.TOWARDS_CAMERA: Reference(image="front.png", source="sketch")}), _props())
    other = Registry(_locations(), {**_characters(), "tomas": Character(id="tomas", name="Tomas", description="changed")}, _props())

    assert needs_drawing(drawn, shot, SCENE, edited) is True
    assert needs_drawing(drawn, shot, SCENE, sketched) is True
    assert needs_drawing(drawn, shot, SCENE, other) is False


def test_a_generated_reference_appearing_on_the_entry_changes_nothing():
    """
    Verifies that the engine recording a generated reference (or plate) doesn't mark anything -- only sketches count.
    """
    shot = Shot(scene_id="s1")
    drawn = _drawn(CharacterLayer(character_id="mara"), shot)
    recorded = Registry(_locations(), _characters(references={Orientation.TOWARDS_CAMERA: Reference(image="r.png", source="generated")}), _props())

    assert needs_drawing(drawn, shot, SCENE, recorded) is False


@pytest.mark.parametrize("change, south_marked, north_marked", [
    ({"description": "a bigger office"}, True, True),
    ({"setting": Setting.EXT}, True, True),
    ({"views": {Facing.NORTH: "a bookcase", Facing.SOUTH: "a door"}}, True, True),  # Every side is drawn from north
    ({"views": {Facing.NORTH: "a window", Facing.SOUTH: "a coat stand"}}, True, False),
    ({"views": {Facing.NORTH: "a window", Facing.SOUTH: "a door", Facing.WEST: "a map"}}, False, False),
    ({"plates": {Facing.SOUTH: Reference(image="s.png", source="sketch")}}, True, False),
])
def test_a_location_edit_marks_only_the_backgrounds_it_reaches(change, south_marked, north_marked):
    """
    Verifies which backgrounds a location edit reaches: anything about the whole place reaches every side; a side's own view or sketch reaches that side (and north's reach every side); another side's reaches neither.

    Arguments:
        change: dict - The edit to the office.
        south_marked: bool - Whether a south-facing background is out of date after it.
        north_marked: bool - Whether a north-facing one is.
    """
    shot = Shot(scene_id="s1")
    south = _drawn(BackgroundLayer(facing=Facing.SOUTH), shot)
    north = _drawn(BackgroundLayer(facing=Facing.NORTH), shot)
    edited = _registry(**change)

    assert (needs_drawing(south, shot, SCENE, edited), needs_drawing(north, shot, SCENE, edited)) == (south_marked, north_marked)


def test_params_recorded_before_registries_counted_mark_the_layer():
    """
    Verifies that a layer whose params predate the registry fields (so record none of them) needs drawing once its character has a description -- which costs nothing when nothing really changed, as its images are found by their keys.
    """
    shot = Shot(scene_id="s1")
    registry = Registry(_locations(), _characters(description="a lighthouse keeper"), _props())
    old = CharacterLayer.model_validate({"character_id": "mara", "image": "x.png", "last_generated_params": {"orientation": "towards_camera", "action": ""}})

    assert needs_drawing(old, shot, SCENE, registry) is True


def test_a_reference_already_recorded_counts_again_once_its_entry_changes():
    """
    Verifies the estimate after an edit: a recorded generated reference is free while nothing changed, but counted once the character's description has (it will be drawn again) -- while a sketched one never is.
    """
    shot = Shot(scene_id="s1")
    recorded = {Orientation.TOWARDS_CAMERA: Reference(image="r.png", source="generated")}
    before = Registry({}, _characters(references=recorded), {})
    drawn = _drawn(CharacterLayer(character_id="mara"), shot, registry=before)
    stale = [Planned(SCENE, shot, drawn)]
    after = Registry({}, _characters(references=recorded, description="a keeper in a red scarf"), {})
    sketched = Registry({}, _characters(references={Orientation.TOWARDS_CAMERA: Reference(image="s.png", source="sketch")}, description="changed"), {})

    assert images_at_most(stale, before) == 0
    assert images_at_most(stale, after) == 1
    assert images_at_most(stale, sketched) == 0
