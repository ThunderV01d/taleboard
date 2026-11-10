"""
Unit tests for layers.

Covers the shared transform and layer defaults, validation of each layer type, round-tripping a layer tree through plain data, and the regeneration dirty-state shared by the three generated layer types.
"""
import pytest
from pydantic import TypeAdapter, ValidationError

from taleboard.schema.enums import Atmosphere, CameraAngle, Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.layers import (
    FRAME_SIZE, BackgroundLayer, BackgroundParams, CharacterLayer, CharacterParams, Corners, FreehandLayer, GeneratedLayer, GenerationContext,
    GroupLayer, ImageLayer, Layer, Point, PropLayer, TextLayer, Transform,
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
    layer.last_generated_params = layer.current_params(context, None)
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
        LAYER.validate_python({"type": "camera"})


@pytest.mark.parametrize("layer", [BackgroundLayer(), CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")])
def test_a_layer_that_was_never_generated_needs_generating(layer):
    """
    Verifies that every generated layer type needs (re)generating until it has been generated once.

    Arguments:
        layer: GeneratedLayer - A layer that hasn't been generated.
    """
    assert layer.needs_regeneration(_context(), None) is True


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
    assert layer.needs_regeneration(context, None) is False

    setattr(layer, *change)
    assert layer.needs_regeneration(context, None) is True

    setattr(layer, *undo)
    assert layer.needs_regeneration(context, None) is False


@pytest.mark.parametrize("layer", [BackgroundLayer(), CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")])
def test_moving_or_restyling_a_layer_never_needs_regeneration(layer):
    """
    Verifies that transform, warp, opacity, visibility and name edits never enable Regenerate -- blocking is free.

    Arguments:
        layer: GeneratedLayer - A layer to generate and then move.
    """
    context = _context()
    _generated(layer, context)

    layer.transform = Transform(x=10, y=20, scale_x=-2, rotation=45, skew_y=5)
    layer.opacity, layer.visible, layer.name = 0.3, False, "renamed"
    layer.corners = Corners(top_left=Point(x=0.1, y=-0.2))

    assert layer.needs_regeneration(context, None) is False


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

    assert background.needs_regeneration(_context(**{field: value}), None) is True


def test_characters_and_props_ignore_the_shot_and_scene():
    """
    Verifies that a character's or prop's image doesn't go out of date when only the shot or scene changes.
    """
    character = _generated(CharacterLayer(character_id="mara", action="waving"), _context())
    prop = _generated(PropLayer(prop_id="lamp"), _context())
    changed = _context(shot_size=ShotSize.WIDE, time_of_day=TimeOfDay.NIGHT)

    assert character.needs_regeneration(changed, None) is False
    assert prop.needs_regeneration(changed, None) is False


def test_current_params_hold_exactly_what_each_image_depends_on():
    """
    Verifies the params each generated layer reports: a background's include its facing plus the whole context, a character's its orientation and action.
    """
    context = _context(details="door open")

    assert BackgroundLayer(facing=Facing.SOUTH).current_params(context, None) == BackgroundParams(facing=Facing.SOUTH, **context.model_dump())
    assert CharacterLayer(character_id="mara", action="waving").current_params(context, None) == CharacterParams(orientation=Orientation.TOWARDS_CAMERA, action="waving")


def test_a_generated_layer_type_that_forgets_its_params_fails_loudly():
    """
    Verifies that the base generated layer refuses to report params -- a new generated type must say what its image depends on.
    """
    with pytest.raises(NotImplementedError):
        GeneratedLayer().current_params(_context(), None)


def test_a_picture_starts_unwarped_and_its_default_corners_are_its_own():
    """
    Verifies that picture layers start with no corners, and that Corners() leaves the picture as it is.
    """
    corners = Corners()

    assert [ImageLayer().corners, BackgroundLayer().corners] == [None, None]
    assert [(p.x, p.y) for p in (corners.top_left, corners.top_right, corners.bottom_right, corners.bottom_left)] == [(0, 0), (1, 0), (1, 1), (0, 1)]


def test_corners_can_be_pulled_outside_the_picture():
    """
    Verifies that corners beyond the picture's edges are allowed -- stretching it outwards.
    """
    corners = Corners(top_left=Point(x=-0.5, y=-0.25), bottom_right=Point(x=1.5, y=2))

    assert (corners.top_left.x, corners.bottom_right.y) == (-0.5, 2)


@pytest.mark.parametrize("changes", [
    {"top_left": Point(x=1, y=0), "top_right": Point(x=0, y=0)},  # Crossed over: the top edge runs backwards
    {"top_left": Point(x=0.8, y=0.8)},  # Pushed in past the diagonal: concave
    {"top_left": Point(x=1, y=0)},  # Onto another corner: flat
    {"top_right": Point(x=0, y=1), "bottom_left": Point(x=1, y=0)},  # Mirrored: anticlockwise
])
def test_corners_that_would_fold_the_picture_are_rejected(changes):
    """
    Verifies that only convex, clockwise corners are accepted, so a warp can't fold or flip the picture.

    Arguments:
        changes: dict - Corners to move from where they start.
    """
    with pytest.raises(ValidationError, match="convex"):
        Corners(**changes)


def test_corners_round_trip_on_picture_layers():
    """
    Verifies that a warped layer's corners survive being saved as plain data and read back.
    """
    layer = PropLayer(prop_id="lamp", corners=Corners(top_right=Point(x=0.9, y=0.1)))

    loaded = LAYER.validate_python(LAYER.dump_python(layer, mode="json"))

    assert loaded == layer


def test_a_freehand_layer_keeps_its_strokes_in_order():
    """
    Verifies that a freehand layer holds its strokes (drawing and erasing) in the order they were drawn, with their pen settings.
    """
    layer = LAYER.validate_python({"type": "freehand", "strokes": [
        {"points": [0, 0, 5, 5], "colour": "#ff0000", "width": 2},
        {"points": [1, 1, 4, 4], "width": 10, "erase": True},
    ]})

    assert isinstance(layer, FreehandLayer)
    assert [(s.colour, s.width, s.erase) for s in layer.strokes] == [("#ff0000", 2, False), ("#000000", 10, True)]


@pytest.mark.parametrize("stroke", [
    {"points": [0, 0, 5]},  # Not x, y pairs
    {"points": []},  # No points
    {"points": [0, 0], "width": 0},
    {"points": [0, 0], "colour": "red"},
])
def test_a_malformed_stroke_is_rejected(stroke):
    """
    Verifies a stroke's checks: its points come in x, y pairs (at least one), its width is positive, and its colour is #rrggbb.

    Arguments:
        stroke: dict - The bad stroke.
    """
    with pytest.raises(ValidationError):
        LAYER.validate_python({"type": "freehand", "strokes": [stroke]})


def test_a_shot_can_hold_freehand_layers_within_the_stroke_budget():
    """
    Verifies that a shot takes freehand layers (inside groups too), but not more stroke points than fit in its stored item.
    """
    from taleboard.schema.storyboard import MAX_STROKE_POINTS, Shot

    small = {"type": "freehand", "strokes": [{"points": [0, 0, 1, 1]}]}
    assert Shot(scene_id="s1", layers=[{"type": "group", "children": [small]}]).all_layers()[1].type == "freehand"
    big = {"type": "freehand", "strokes": [{"points": [0.0, 0.0] * (MAX_STROKE_POINTS + 1)}]}
    with pytest.raises(ValidationError, match="at most"):
        Shot(scene_id="s1", layers=[big])
