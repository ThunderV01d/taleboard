"""
Unit tests for layers.

Covers the shared transform and layer defaults, validation of each layer type, round-tripping a layer tree through plain data, and the regeneration dirty-state shared by the three generated layer types.
"""
import pytest
from pydantic import TypeAdapter, ValidationError

from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.layers import (
    FRAME_SIZE, BackgroundLayer, BackgroundParams, CharacterLayer, CharacterParams, GeneratedLayer, GenerationContext,
    GroupLayer, ImageLayer, Layer, PropLayer, TextLayer, Transform,
)

LAYER = TypeAdapter(Layer)


def _context(**changes) -> GenerationContext:
    """
    Builds a generation context for a medium, eye-level shot in the office on a clear day, with any fields changed.

    Arguments:
        changes: dict - Fields to change from the defaults.

    Returns:
        GenerationContext - A GenerationContext object.
    """
    return GenerationContext(**{
        "location_id": "office", "shot_size": ShotSize.MEDIUM, "angle": CameraAngle.EYE_LEVEL, "details": "",
        "time_of_day": TimeOfDay.DAY, "atmosphere": Atmosphere.CLEAR, **changes,
    })


def _generated(layer: GeneratedLayer, context: GenerationContext) -> GeneratedLayer:
    """
    Marks a layer as just generated, the way a generation job does -- its current params become its baseline.

    Arguments:
        layer: GeneratedLayer - Layer to mark.
        context: GenerationContext - The context it was generated in.

    Returns:
        GeneratedLayer - The same layer.
    """
    layer.last_generated_params = layer.current_params(context)
    return layer


def test_a_new_layer_sits_unchanged_at_the_centre_of_the_frame():
    """
    Verifies that a layer's default transform is the identity, centred in the frame, and that it starts solid and visible.
    """
    layer = TextLayer()

    assert (layer.transform.x, layer.transform.y) == (FRAME_SIZE / 2, FRAME_SIZE / 2)
    assert layer.transform == Transform(x=FRAME_SIZE / 2, y=FRAME_SIZE / 2)
    assert (layer.opacity, layer.visible) == (1.0, True)


def test_every_layer_gets_its_own_id_and_transform():
    """
    Verifies that layer IDs and transforms are created per layer -- a shared default would make every layer the same object.
    """
    first, second = TextLayer(), TextLayer()
    first.transform.x = 10

    assert first.id != second.id
    assert second.transform.x == FRAME_SIZE / 2


def test_a_negative_scale_is_allowed_as_a_flip():
    """
    Verifies that flipping is expressed as a negative scale, not rejected.
    """
    assert Transform(scale_x=-1).scale_x == -1


@pytest.mark.parametrize("opacity", [-0.1, 1.1])
def test_opacity_must_be_between_0_and_1(opacity):
    """
    Verifies that an opacity outside 0-1 is rejected.

    Arguments:
        opacity: float - An out-of-range opacity.
    """
    with pytest.raises(ValidationError):
        TextLayer(opacity=opacity)


@pytest.mark.parametrize("colour", ["red", "#fff", "#12345g", "000000"])
def test_text_colour_must_be_a_six_digit_hex_code(colour):
    """
    Verifies that a text colour is only accepted as #rrggbb.

    Arguments:
        colour: str - An invalid colour.
    """
    with pytest.raises(ValidationError):
        TextLayer(colour=colour)


def test_text_rejects_an_unknown_font_or_a_size_of_zero():
    """
    Verifies that text only takes one of the generic fonts, and a positive size.
    """
    with pytest.raises(ValidationError):
        TextLayer(font="comic-sans")
    with pytest.raises(ValidationError):
        TextLayer(size=0)


def test_a_character_action_is_capped_like_the_breakdowns():
    """
    Verifies that a character's action keeps the 200-character cap the breakdown's actions have.
    """
    CharacterLayer(character_id="mara", action="x" * 200)
    with pytest.raises(ValidationError):
        CharacterLayer(character_id="mara", action="x" * 201)


def test_character_and_prop_layers_must_say_who_or_what_they_show():
    """
    Verifies that a character layer needs a character_id, and a prop layer a prop_id.
    """
    with pytest.raises(ValidationError):
        CharacterLayer()
    with pytest.raises(ValidationError):
        PropLayer()


def test_a_layer_tree_round_trips_through_plain_data_as_the_right_types():
    """
    Verifies that a nested layer tree saved as plain data (as it is stored) is read back with every layer as its own type, groups within groups included.
    """
    tree = GroupLayer(children=[
        CharacterLayer(character_id="mara", action="waving"),
        GroupLayer(children=[PropLayer(prop_id="lamp"), TextLayer(text="Hi")]),
        ImageLayer(image="uploads/x.png"),
    ])

    back = LAYER.validate_python(tree.model_dump(mode="json"))

    assert back == tree
    assert [type(child).__name__ for child in back.children] == ["CharacterLayer", "GroupLayer", "ImageLayer"]
    assert [type(child).__name__ for child in back.children[1].children] == ["PropLayer", "TextLayer"]


def test_a_layer_with_an_unknown_type_is_rejected():
    """
    Verifies that the discriminated union refuses a layer whose type isn't one of the six.
    """
    with pytest.raises(ValidationError):
        LAYER.validate_python({"type": "freehand"})


@pytest.mark.parametrize("layer", [BackgroundLayer(), CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")])
def test_a_layer_that_was_never_generated_needs_generating(layer):
    """
    Verifies that every generated layer type needs (re)generating until it has been generated once.

    Arguments:
        layer: GeneratedLayer - A layer that hasn't been generated.
    """
    assert layer.needs_regeneration(_context()) is True


@pytest.mark.parametrize("layer, change, undo", [
    (BackgroundLayer(), ("facing", Facing.EAST), ("facing", Facing.NORTH)),
    (CharacterLayer(character_id="mara", action="waving"), ("orientation", Orientation.LEFT), ("orientation", Orientation.TOWARDS_CAMERA)),
    (CharacterLayer(character_id="mara", action="waving"), ("action", "sitting"), ("action", "waving")),
    (PropLayer(prop_id="lamp"), ("orientation", Orientation.RIGHT), ("orientation", Orientation.TOWARDS_CAMERA)),
])
def test_regeneration_is_needed_after_a_change_and_not_after_undoing_it(layer, change, undo):
    """
    Verifies the snapshot-diff behaviour shared by every generated layer: a change to a value its image depends on enables Regenerate, and changing it back disables it again.

    Arguments:
        layer: GeneratedLayer - A layer to generate and edit.
        change: tuple[str,object] - Field to change, and its new value.
        undo: tuple[str,object] - The same field, and its original value.
    """
    context = _context()
    _generated(layer, context)
    assert layer.needs_regeneration(context) is False

    setattr(layer, *change)
    assert layer.needs_regeneration(context) is True

    setattr(layer, *undo)
    assert layer.needs_regeneration(context) is False


@pytest.mark.parametrize("layer", [BackgroundLayer(), CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")])
def test_moving_or_restyling_a_layer_never_needs_regeneration(layer):
    """
    Verifies that transform, opacity, visibility and name edits never enable Regenerate -- blocking is free.

    Arguments:
        layer: GeneratedLayer - A layer to generate and then move.
    """
    context = _context()
    _generated(layer, context)

    layer.transform = Transform(x=10, y=20, scale_x=-2, rotation=45, skew_y=5)
    layer.opacity, layer.visible, layer.name = 0.3, False, "renamed"

    assert layer.needs_regeneration(context) is False


@pytest.mark.parametrize("field, value", [
    ("location_id", "quay"), ("shot_size", ShotSize.CLOSE_UP), ("angle", CameraAngle.LOW), ("details", "rain on the window"),
    ("time_of_day", TimeOfDay.NIGHT), ("atmosphere", Atmosphere.FOGGY),
])
def test_a_background_needs_regeneration_when_its_shot_or_scene_changes(field, value):
    """
    Verifies that a background's image also depends on its scene's location and lighting and its shot's framing and details, not just its own facing.

    Arguments:
        field: str - Context field to change.
        value: object - Its new value.
    """
    background = _generated(BackgroundLayer(), _context())

    assert background.needs_regeneration(_context(**{field: value})) is True


def test_characters_and_props_ignore_the_shot_and_scene():
    """
    Verifies that a character's or prop's image doesn't go out of date when only the shot or scene changes.
    """
    character = _generated(CharacterLayer(character_id="mara", action="waving"), _context())
    prop = _generated(PropLayer(prop_id="lamp"), _context())
    changed = _context(shot_size=ShotSize.WIDE, time_of_day=TimeOfDay.NIGHT)

    assert character.needs_regeneration(changed) is False
    assert prop.needs_regeneration(changed) is False


def test_current_params_hold_exactly_what_each_image_depends_on():
    """
    Verifies the params each generated layer reports: a background's include its facing plus the whole context, a character's its orientation and action.
    """
    context = _context(details="door open")

    assert BackgroundLayer(facing=Facing.SOUTH).current_params(context) == BackgroundParams(facing=Facing.SOUTH, **context.model_dump())
    assert CharacterLayer(character_id="mara", action="waving").current_params(context) == CharacterParams(orientation=Orientation.TOWARDS_CAMERA, action="waving")


def test_a_generated_layer_type_that_forgets_its_params_fails_loudly():
    """
    Verifies that the base generated layer refuses to report params -- a new generated type must say what its image depends on.
    """
    with pytest.raises(NotImplementedError):
        GeneratedLayer().current_params(_context())
