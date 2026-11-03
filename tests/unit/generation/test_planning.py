"""
Unit tests for planning what a Generate request draws.

Covers which layers need drawing (never drawn, or changed since), their order, and the most images drawing them can take -- each image counted once however many layers share it.
"""
import pytest

from taleboard.generation.planning import Planned, images_at_most, layers_to_draw, needs_drawing
from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, Setting, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Prop, Reference, Scene, Shot

SCENE = Scene(id="s1", location_id="office")


def _locations(**changes) -> dict[str, Location]:
    return {"office": Location(id="office", name="Office", views={Facing.NORTH: "a window", Facing.SOUTH: "a door"}, **changes)}


def _characters(**changes) -> dict[str, Character]:
    return {"mara": Character(id="mara", name="Mara", **changes)}


def _props() -> dict[str, Prop]:
    return {"lamp": Prop(id="lamp", name="Lamp")}


def _drawn(layer, shot: Shot, scene: Scene = SCENE):
    """
    The layer as if just generated: an image, and the params it was drawn from.
    """
    return layer.model_copy(update={"image": "x.png", "last_generated_params": layer.current_params(shot.generation_context(scene))})


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

    assert needs_drawing(mara, shot, SCENE) is True
    assert needs_drawing(drawn, shot, SCENE) is False
    assert needs_drawing(drawn.model_copy(update={"action": "sitting"}), shot, SCENE) is True


def test_only_the_layers_that_need_it_are_drawn_in_story_order():
    """
    Verifies that layers_to_draw goes shot by shot, bottom to top (into groups too), skipping text, images and layers already up to date.
    """
    first = Shot(scene_id="s1", order=0)
    first.layers = [BackgroundLayer(id="bg1"), GroupLayer(children=[CharacterLayer(id="mara", character_id="mara"), TextLayer()])]
    second = Shot(scene_id="s1", order=1)
    second.layers = [_drawn(BackgroundLayer(id="bg2"), second), PropLayer(id="lamp", prop_id="lamp")]

    planned = layers_to_draw([(SCENE, first), (SCENE, second)])

    assert [p.layer.id for p in planned] == ["bg1", "mara", "lamp"]
    assert [p.shot.id for p in planned] == [first.id, first.id, second.id]


def test_a_plain_background_is_at_most_one_image_its_plate():
    """
    Verifies the cheapest background: a wide, eye-level shot by day, with no details, is just its plate.
    """
    assert images_at_most(_planned(BackgroundLayer(), shot_size=ShotSize.WIDE), _locations(), {}, {}) == 1


def test_every_link_of_a_background_chain_counts():
    """
    Verifies that a south, medium, low-angle shot with details, at night, counts north and south plates, framing, details and lighting.
    """
    night = Scene(id="s2", location_id="office", time_of_day=TimeOfDay.NIGHT)
    planned = _planned(BackgroundLayer(facing=Facing.SOUTH), scene=night, shot_size=ShotSize.MEDIUM, angle=CameraAngle.LOW, details="the lamp lit")

    assert images_at_most(planned, _locations(), {}, {}) == 5


def test_plates_already_on_the_entry_are_not_counted():
    """
    Verifies that recorded plates cost nothing -- including the north one a south plate is drawn from.
    """
    locations = _locations(plates={Facing.NORTH: "n.png", Facing.SOUTH: "s.png"})

    assert images_at_most(_planned(BackgroundLayer(facing=Facing.SOUTH), shot_size=ShotSize.WIDE), locations, {}, {}) == 0


def test_a_side_with_no_view_counts_as_the_north_plate():
    """
    Verifies that facing a side nothing has been said about counts only the north plate, as that's what it shows.
    """
    assert images_at_most(_planned(BackgroundLayer(facing=Facing.EAST), shot_size=ShotSize.WIDE), _locations(), {}, {}) == 1


def test_a_close_up_counts_as_its_wide_background():
    """
    Verifies that a close-up costs what a wide shot of the same angle does -- it uses the wide background.
    """
    close_up = _planned(BackgroundLayer(), shot_size=ShotSize.CLOSE_UP, angle=CameraAngle.HIGH)
    wide = _planned(BackgroundLayer(), shot_size=ShotSize.WIDE, angle=CameraAngle.HIGH)

    assert images_at_most(close_up, _locations(), {}, {}) == images_at_most(wide, _locations(), {}, {}) == 2


def test_images_shared_by_many_layers_count_once():
    """
    Verifies that two shots with the same background, and two layers with the same pose, count each image once.
    """
    planned = (
        _planned(BackgroundLayer(), CharacterLayer(character_id="mara", action="waving"), shot_size=ShotSize.MEDIUM)
        + _planned(BackgroundLayer(), CharacterLayer(character_id="mara", action="waving"), shot_size=ShotSize.MEDIUM)
    )

    # Plate + medium framing, Mara's front reference + her pose
    assert images_at_most(planned, _locations(), _characters(), {}) == 4


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

    assert images_at_most(planned, {}, _characters(references=references), {}) == expected


def test_a_prop_is_only_ever_its_references():
    """
    Verifies that a prop facing away counts its front and back references, and nothing else.
    """
    assert images_at_most(_planned(PropLayer(prop_id="lamp", orientation=Orientation.AWAY_FROM_CAMERA)), {}, {}, _props()) == 2


def test_an_exterior_in_the_rain_counts_its_lighting_and_daylight_does_not():
    """
    Verifies that lighting counts only when there is something to light -- for an exterior as for an interior.
    """
    rainy = Scene(id="s3", location_id="office", atmosphere=Atmosphere.RAINY)
    exterior = _locations(setting=Setting.EXT)

    assert images_at_most(_planned(BackgroundLayer(), scene=rainy, shot_size=ShotSize.WIDE), exterior, {}, {}) == 2
    assert images_at_most(_planned(BackgroundLayer(), shot_size=ShotSize.WIDE), exterior, {}, {}) == 1
