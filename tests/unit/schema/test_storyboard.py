"""
Unit tests for storyboard.

Covers the registry entries' per-orientation and per-facing images, scenes always having a location, and shots: flattening their layer tree, building their generation context, rejecting duplicate layer IDs, and round-tripping through plain data.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from taleboard.schema.enums import Setting, Atmosphere, Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, ImageLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Project, Prop, Reference, Scene, Shot


def _scene(**changes) -> Scene:
    """
    Builds a scene set in an office, with any fields changed.

    Arguments:
        changes: dict - Fields to change from the defaults.

    Returns:
        Scene - A Scene object.
    """
    return Scene(**{"location_id": "office", **changes})


def test_a_character_starts_with_no_references_and_gains_one_per_orientation():
    """
    Verifies that references are added lazily, one per orientation, and that each records whether it was generated or sketched.
    """
    mara = Character(id="mara", name="Mara")
    assert mara.references == {}

    mara.references[Orientation.LEFT] = Reference(image="refs/mara-left.png", source="sketch")

    assert Orientation.LEFT in mara.references
    assert Orientation.RIGHT not in mara.references
    assert mara.references[Orientation.LEFT].source == "sketch"


def test_references_only_accept_real_orientations_and_sources():
    """
    Verifies that a reference can't be stored under an unknown orientation, or with an unknown source.
    """
    with pytest.raises(ValidationError):
        Character(id="mara", name="Mara", references={"upside_down": {"image": "x.png", "source": "generated"}})
    with pytest.raises(ValidationError):
        Reference(image="x.png", source="downloaded")


def test_a_location_starts_with_no_plates_and_only_takes_compass_facings():
    """
    Verifies that plates are added lazily, one per facing, and only under the four compass facings.
    """
    office = Location(id="office", name="Office", plates={"north": "plates/office-north.png"})

    assert office.plates == {Facing.NORTH: "plates/office-north.png"}
    with pytest.raises(ValidationError):
        Location(id="office", name="Office", plates={"up": "x.png"})


@pytest.mark.parametrize("model, fields", [(Character, {"id": "mara", "name": "Mara"}), (Prop, {"id": "lamp", "name": "Lamp"}), (Location, {"id": "office", "name": "Office"})])
def test_registry_descriptions_keep_the_breakdowns_300_character_cap(model, fields):
    """
    Verifies that every registry entry's description is capped like the breakdown's, so generated text always fits.

    Arguments:
        model: type - Registry entry model.
        fields: dict - Its required fields.
    """
    model(**fields, description="x" * 300)
    with pytest.raises(ValidationError):
        model(**fields, description="x" * 301)


def test_a_scene_must_have_a_location_and_defaults_to_a_clear_day():
    """
    Verifies that a scene can't be created without a location, and that its lighting defaults to a clear day.
    """
    with pytest.raises(ValidationError):
        Scene()

    scene = _scene()
    assert (scene.time_of_day, scene.atmosphere) == (TimeOfDay.DAY, Atmosphere.CLEAR)
    assert scene.id != _scene().id


@pytest.mark.parametrize("model, fields", [(Scene, {"location_id": "office"}), (Shot, {"scene_id": "s"})])
def test_order_cannot_be_negative(model, fields):
    """
    Verifies that scene and shot positions start at 0.

    Arguments:
        model: type - Scene or Shot.
        fields: dict - Its required fields.
    """
    with pytest.raises(ValidationError):
        model(**fields, order=-1)


def test_a_shot_has_sensible_defaults_and_validates_its_framing():
    """
    Verifies a new shot's defaults, and that its duration and details stay within the breakdown's limits.
    """
    shot = Shot(scene_id="s")
    assert (shot.layers, shot.version, shot.duration_s, shot.details) == ([], 0, 2.0, "")

    for bad in ({"duration_s": 0}, {"duration_s": 61}, {"details": "x" * 151}, {"shot_size": "extreme_close_up"}):
        with pytest.raises(ValidationError):
            Shot(scene_id="s", **bad)


def test_all_layers_flattens_groups_in_drawing_order():
    """
    Verifies that all_layers lists every layer, groups' children included at any depth, bottom to top.
    """
    shot = Shot(scene_id="s", layers=[
        BackgroundLayer(id="bg"),
        GroupLayer(id="g1", children=[CharacterLayer(id="mara", character_id="mara"), GroupLayer(id="g2", children=[PropLayer(id="lamp", prop_id="lamp")])]),
        TextLayer(id="caption"),
    ])

    assert [layer.id for layer in shot.all_layers()] == ["bg", "g1", "mara", "g2", "lamp", "caption"]


def test_two_layers_with_the_same_id_are_rejected_even_inside_groups():
    """
    Verifies that layer IDs must be unique across the whole tree, as layers are edited and regenerated by ID.
    """
    with pytest.raises(ValidationError, match="same id"):
        Shot(scene_id="s", layers=[TextLayer(id="a"), GroupLayer(children=[ImageLayer(id="a")])])


def test_the_generation_context_combines_the_shots_framing_with_its_scenes_lighting():
    """
    Verifies that a shot's generation context takes its framing and details from the shot, and its location and lighting from its scene.
    """
    shot = Shot(scene_id="s", shot_size=ShotSize.CLOSE_UP, details="door open")
    scene = _scene(time_of_day=TimeOfDay.NIGHT, atmosphere=Atmosphere.RAINY)

    context = shot.generation_context(scene)

    assert (context.location_id, context.shot_size, context.details, context.time_of_day, context.atmosphere) == ("office", ShotSize.CLOSE_UP, "door open", TimeOfDay.NIGHT, Atmosphere.RAINY)


def test_changing_a_scenes_lighting_makes_its_shots_backgrounds_need_regenerating():
    """
    Verifies the whole chain: a background generated for a scene goes out of date when that scene's time of day changes.
    """
    scene = _scene()
    shot = Shot(scene_id=scene.id, layers=[BackgroundLayer()])
    background = shot.layers[0]
    background.last_generated_params = background.current_params(shot.generation_context(scene))
    assert background.needs_regeneration(shot.generation_context(scene)) is False

    scene.time_of_day = TimeOfDay.DUSK

    assert background.needs_regeneration(shot.generation_context(scene)) is True


def test_moving_a_scene_to_another_location_makes_its_shots_backgrounds_need_regenerating():
    """
    Verifies that a background records which location it was drawn from, so moving its scene elsewhere puts it out of date.
    """
    scene = _scene()
    shot = Shot(scene_id=scene.id, layers=[BackgroundLayer()])
    background = shot.layers[0]
    background.last_generated_params = background.current_params(shot.generation_context(scene))

    scene.location_id = "quay"

    assert background.needs_regeneration(shot.generation_context(scene)) is True


def test_a_shot_round_trips_through_plain_data():
    """
    Verifies that a shot saved as JSON (as it is stored) loads back identical, layer types and generation snapshots included.
    """
    scene = _scene()
    character = CharacterLayer(character_id="mara", action="waving", image="poses/mara.png")
    shot = Shot(scene_id=scene.id, layers=[BackgroundLayer(facing=Facing.WEST), GroupLayer(children=[character])])
    character.last_generated_params = character.current_params(shot.generation_context(scene))

    assert Shot.model_validate_json(shot.model_dump_json()) == shot


def test_a_project_needs_a_name_and_an_owner_and_gets_its_own_id():
    """
    Verifies that a project's name can't be empty, that it must have an owner, and that each new project gets a different ID.
    """
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        Project(name="", owner_id="mara", created_at=now)

    assert Project(name="A", owner_id="mara", created_at=now).project_id != Project(name="B", owner_id="mara", created_at=now).project_id
    with pytest.raises(ValidationError):
        Project(name="A", created_at=now)  # Every project has an owner


def test_a_location_is_indoors_with_no_views_unless_told_otherwise():
    """
    Verifies a location's defaults -- an interior, with nothing said about any side -- and that views are keyed by compass facing.
    """
    office = Location(id="office", name="Office")
    quay = Location(id="quay", name="Quay", setting="exterior", views={"north": "the harbour", "south": "a row of cottages"})

    assert (office.setting, office.views) == (Setting.INT, {})
    assert (quay.setting, quay.views) == (Setting.EXT, {Facing.NORTH: "the harbour", Facing.SOUTH: "a row of cottages"})
    with pytest.raises(ValidationError):
        Location(id="office", name="Office", setting="underground")
    with pytest.raises(ValidationError):
        Location(id="office", name="Office", views={"up": "the ceiling"})


def test_each_view_is_capped_so_a_plate_prompt_stays_short():
    """
    Verifies that one side's view can be up to 200 characters, and no more.
    """
    Location(id="office", name="Office", views={"north": "x" * 200})
    with pytest.raises(ValidationError):
        Location(id="office", name="Office", views={"north": "x" * 201})
