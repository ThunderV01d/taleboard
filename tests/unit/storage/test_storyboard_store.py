"""
Unit tests for storyboard_store.

Runs against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py), so no AWS calls are made.

Covers projects, the three registries (ID suffixing, per-orientation references, create-only vs update-only writes), scenes (order, and deleting a scene's shots with it), and shots (layer graphs round-tripping, and the version check that refuses a save from an out-of-date copy).
"""
import pytest
from pydantic import ValidationError

from taleboard.schema.enums import Facing, Orientation, ShotSize, TimeOfDay
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer, TextLayer, Transform
from taleboard.schema.storyboard import Character, Location, Prop, Reference, Scene, Shot
from taleboard.storage.storyboard_store import ShotConflictError, StoryboardStore, owner_index_key, registry_sk, scene_sk, shot_sk

OWNER = "mara-user"


@pytest.fixture
def boards(aws):
    """
    A StoryboardStore backed by the shared fakes.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes (they also set the TALEBOARD_* environment variables).

    Returns:
        StoryboardStore - A store backed by the fakes.
    """
    return StoryboardStore.from_env()


@pytest.fixture
def pid(boards):
    """
    The ID of a fresh, empty project.

    Arguments:
        boards: StoryboardStore - The fake-backed store.

    Returns:
        str - The project's ID.
    """
    return boards.create_project("Lighthouse", OWNER).project_id


def _shot(scene_id: str, order: int = 0, **changes) -> Shot:
    """
    Builds a shot with a background, a caption, and a group holding a character and a prop.

    Arguments:
        scene_id: str - The shot's scene.
        order: int - Position of the shot in its scene. Defaults to 0.
        changes: dict - Fields to change from the defaults.

    Returns:
        Shot - A Shot object.
    """
    return Shot(scene_id=scene_id, order=order, layers=[
        BackgroundLayer(facing=Facing.EAST),
        GroupLayer(children=[
            CharacterLayer(character_id="mara", action="waving", transform=Transform(x=300.25, y=812.5, scale_x=-0.85, rotation=12.5)),
            PropLayer(prop_id="lamp", opacity=0.4),
        ]),
        TextLayer(text="Hello", colour="#336699"),
    ], **changes)


def test_sort_keys_follow_the_planned_layout():
    """
    Verifies the sort-key layout, with a shot's key starting with its scene's.
    """
    assert registry_sk(Character, "mara") == "CHARACTER#mara"
    assert registry_sk(Prop, "lamp") == "PROP#lamp"
    assert registry_sk(Location, "office") == "LOCATION#office"
    assert scene_sk("s1") == "SCENE#s1"
    assert shot_sk("s1", "h1") == "SHOT#s1#h1"
    assert owner_index_key("u1") == "OWNER#u1"


def test_a_project_is_created_found_and_listed(boards):
    """
    Verifies that a new project can be got back by ID, and is listed.
    """
    project = boards.create_project("Lighthouse", OWNER)

    assert boards.get_project(project.project_id) == project
    assert project in boards.list_projects(OWNER)


def test_a_project_records_its_owner_and_is_only_listed_for_them(boards):
    """
    Verifies that a project keeps its owner, and that each user's list holds only their own projects.
    """
    mine = boards.create_project("Mine", OWNER)
    theirs = boards.create_project("Theirs", "someone-else")

    assert boards.get_project(mine.project_id).owner_id == OWNER
    assert boards.list_projects(OWNER) == [mine]
    assert boards.list_projects("someone-else") == [theirs]
    assert boards.list_projects("nobody") == []


def test_renaming_keeps_the_owner(boards, pid):
    """
    Verifies that a rename changes only the name -- the placeholder owner used to validate it is never written.
    """
    assert boards.rename_project(pid, "The Lighthouse").owner_id == OWNER
    assert boards.get_project(pid).owner_id == OWNER


def test_projects_are_listed_newest_first(boards):
    """
    Verifies that the projects index lists projects newest first.
    """
    for name in ("First", "Second", "Third"):
        boards.create_project(name, OWNER)

    listed = boards.list_projects(OWNER)

    assert [p.created_at for p in listed] == sorted((p.created_at for p in listed), reverse=True)


def test_a_project_can_be_renamed_but_not_to_nothing(boards, pid):
    """
    Verifies that renaming changes only the name, and that an empty name is refused before anything is written.
    """
    created_at = boards.get_project(pid).created_at

    renamed = boards.rename_project(pid, "The Lighthouse")

    assert (renamed.name, renamed.created_at) == ("The Lighthouse", created_at)
    assert boards.get_project(pid).name == "The Lighthouse"
    with pytest.raises(ValidationError):
        boards.rename_project(pid, "")
    assert boards.get_project(pid).name == "The Lighthouse"


def test_a_missing_project_is_a_key_error_and_is_never_created_by_renaming(boards):
    """
    Verifies that getting or renaming a project that doesn't exist raises a KeyError, and that renaming it doesn't create it.
    """
    with pytest.raises(KeyError):
        boards.get_project("nope")
    with pytest.raises(KeyError):
        boards.rename_project("nope", "Anything")
    with pytest.raises(KeyError):
        boards.get_project("nope")


@pytest.mark.parametrize("model", [Character, Prop, Location])
def test_a_registry_entry_gets_an_id_from_its_name_and_a_suffix_when_taken(boards, pid, model):
    """
    Verifies that every registry slugifies an entry's name into its ID, and settles a clash with "_2", "_3".

    Arguments:
        model: type - Character, Prop or Location.
    """
    first = boards.create_entry(pid, model, "The Old Lamp")
    second = boards.create_entry(pid, model, "The Old Lamp")
    third = boards.create_entry(pid, model, "the old lamp")

    assert [first.id, second.id, third.id] == ["the_old_lamp", "the_old_lamp_2", "the_old_lamp_3"]
    assert [entry.id for entry in boards.list_entries(pid, model)] == ["the_old_lamp", "the_old_lamp_2", "the_old_lamp_3"]


def test_the_registries_are_separate(boards, pid):
    """
    Verifies that a character, a prop and a location can share a name (and ID) without clashing, and are listed only in their own registry.
    """
    boards.create_entry(pid, Character, "Lamp")
    boards.create_entry(pid, Prop, "Lamp")
    boards.create_entry(pid, Location, "Lamp")

    for model in (Character, Prop, Location):
        assert [(type(e), e.id) for e in boards.list_entries(pid, model)] == [(model, "lamp")]


def test_a_registry_entry_round_trips_with_its_references_and_plates(boards, pid):
    """
    Verifies that per-orientation references and per-facing plates (enum-keyed maps) come back exactly as saved.
    """
    mara = boards.create_entry(pid, Character, "Mara", description="A wiry woman in an oilskin coat.", aliases=["the keeper"])
    mara.references[Orientation.LEFT] = Reference(image="refs/mara-left.png", source="sketch")
    mara.references[Orientation.TOWARDS_CAMERA] = Reference(image="refs/mara-front.png", source="generated")
    boards.save_entry(pid, mara)
    office = boards.create_entry(pid, Location, "Office", plates={Facing.NORTH: "plates/office-n.png"})

    assert boards.get_entry(pid, Character, "mara") == mara
    assert boards.get_entry(pid, Location, "office") == office
    assert boards.get_entry(pid, Character, "mara").references[Orientation.LEFT].source == "sketch"


def test_saving_an_entry_replaces_it_but_never_creates_one(boards, pid):
    """
    Verifies that save_entry updates an existing entry, and refuses (with a KeyError) one that was never created.
    """
    lamp = boards.create_entry(pid, Prop, "Lamp")
    boards.save_entry(pid, lamp.model_copy(update={"description": "A brass oil lamp."}))

    assert boards.get_entry(pid, Prop, "lamp").description == "A brass oil lamp."
    with pytest.raises(KeyError):
        boards.save_entry(pid, Prop(id="ghost", name="Ghost"))
    with pytest.raises(KeyError):
        boards.get_entry(pid, Prop, "ghost")


def test_an_invalid_entry_is_refused_before_anything_is_written(boards, pid):
    """
    Verifies that create_entry validates the entry (here, an over-long description) before writing it.
    """
    with pytest.raises(ValidationError):
        boards.create_entry(pid, Character, "Mara", description="x" * 301)

    assert boards.list_entries(pid, Character) == []


def test_deleting_an_entry_removes_only_that_entry(boards, pid):
    """
    Verifies that delete_entry removes one entry and leaves the rest of its registry alone.
    """
    boards.create_entry(pid, Character, "Mara")
    boards.create_entry(pid, Character, "Tomas")

    boards.delete_entry(pid, Character, "mara")

    assert [c.id for c in boards.list_entries(pid, Character)] == ["tomas"]
    with pytest.raises(KeyError):
        boards.get_entry(pid, Character, "mara")


def test_registries_are_scoped_to_their_project(boards, pid):
    """
    Verifies that two projects' registries never mix.
    """
    other = boards.create_project("Other", OWNER).project_id
    boards.create_entry(pid, Character, "Mara")

    assert boards.list_entries(other, Character) == []
    assert boards.create_entry(other, Character, "Mara").id == "mara"  # No clash with the first project's Mara


def test_scenes_are_listed_in_their_order(boards, pid):
    """
    Verifies that scenes come back sorted by order, not by when they were created or by ID.
    """
    for order, name in [(2, "Third"), (0, "First"), (1, "Second")]:
        boards.create_scene(pid, Scene(name=name, order=order, location_id="office"))

    assert [scene.name for scene in boards.list_scenes(pid)] == ["First", "Second", "Third"]


def test_a_scene_round_trips_and_can_be_saved_but_not_created_by_saving(boards, pid):
    """
    Verifies that a scene comes back as created, that save_scene updates it, and that saving one that doesn't exist raises a KeyError.
    """
    scene = Scene(name="Night watch", location_id="lamp_room", time_of_day=TimeOfDay.NIGHT)
    boards.create_scene(pid, scene)
    assert boards.get_scene(pid, scene.id) == scene

    boards.save_scene(pid, scene.model_copy(update={"time_of_day": TimeOfDay.DAWN}))

    assert boards.get_scene(pid, scene.id).time_of_day == TimeOfDay.DAWN
    with pytest.raises(KeyError):
        boards.save_scene(pid, Scene(location_id="office"))


def test_a_shot_round_trips_with_its_whole_layer_graph(boards, pid):
    """
    Verifies that a shot comes back identical -- nested groups, layer types, float transforms (stored as Decimals) and generation snapshots included.
    """
    scene = Scene(location_id="office")
    shot = _shot(scene.id, shot_size=ShotSize.CLOSE_UP, details="door open")
    character = shot.layers[1].children[0]
    character.last_generated_params = character.current_params(shot.generation_context(scene))
    boards.create_shot(pid, shot)

    loaded = boards.get_shot(pid, scene.id, shot.id)

    assert loaded == shot
    assert loaded.layers[1].children[0].transform.scale_x == -0.85


def test_shots_are_listed_per_scene_in_their_order(boards, pid):
    """
    Verifies that listing a scene's shots returns only that scene's shots, sorted by order.
    """
    first, second = Scene(location_id="office"), Scene(location_id="quay")
    for order in (2, 0, 1):
        boards.create_shot(pid, _shot(first.id, order=order, description=f"first {order}"))
    boards.create_shot(pid, _shot(second.id, description="second 0"))

    assert [s.description for s in boards.list_shots(pid, first.id)] == ["first 0", "first 1", "first 2"]
    assert [s.description for s in boards.list_shots(pid, second.id)] == ["second 0"]


def test_saving_a_shot_bumps_its_version_and_the_returned_copy_saves_again(boards, pid):
    """
    Verifies that each save moves the version on by one, and that saving again from the returned copy works -- an editor's second save never conflicts with its own first.
    """
    shot = _shot("s1")
    boards.create_shot(pid, shot)

    saved = boards.save_shot(pid, shot.model_copy(update={"description": "edited"}))
    saved_again = boards.save_shot(pid, saved.model_copy(update={"duration_s": 4.0}))

    assert (saved.version, saved_again.version) == (1, 2)
    stored = boards.get_shot(pid, "s1", shot.id)
    assert (stored.version, stored.description, stored.duration_s) == (2, "edited", 4.0)


def test_saving_from_an_out_of_date_copy_is_refused_and_loses_nothing(boards, pid):
    """
    Verifies optimistic locking: of two copies loaded at the same version, the second to save gets a ShotConflictError (naming the current version), and the first one's changes survive.
    """
    boards.create_shot(pid, _shot("s1"))
    shot_id = boards.list_shots(pid, "s1")[0].id
    tab_a = boards.get_shot(pid, "s1", shot_id)
    tab_b = boards.get_shot(pid, "s1", shot_id)

    boards.save_shot(pid, tab_a.model_copy(update={"description": "from tab A"}))
    with pytest.raises(ShotConflictError) as conflict:
        boards.save_shot(pid, tab_b.model_copy(update={"description": "from tab B"}))

    assert conflict.value.current_version == 1
    assert boards.get_shot(pid, "s1", shot_id).description == "from tab A"


def test_saving_a_deleted_shot_is_a_key_error_not_a_conflict(boards, pid):
    """
    Verifies that saving a shot that has since been deleted raises a KeyError, and doesn't bring it back.
    """
    shot = _shot("s1")
    boards.create_shot(pid, shot)
    boards.delete_shot(pid, "s1", shot.id)

    with pytest.raises(KeyError):
        boards.save_shot(pid, shot)
    assert boards.list_shots(pid, "s1") == []


def test_creating_a_shot_twice_is_refused(boards, pid):
    """
    Verifies that create_shot never overwrites an existing shot.
    """
    shot = _shot("s1")
    boards.create_shot(pid, shot)

    with pytest.raises(Exception, match="ConditionalCheckFailed"):
        boards.create_shot(pid, shot)


def test_deleting_a_scene_deletes_its_shots_but_no_one_elses(boards, pid):
    """
    Verifies that delete_scene removes the scene and every shot in it, and leaves other scenes and their shots alone.
    """
    doomed, kept = Scene(location_id="office"), Scene(location_id="quay", order=1)
    boards.create_scene(pid, doomed)
    boards.create_scene(pid, kept)
    for order in range(3):
        boards.create_shot(pid, _shot(doomed.id, order=order))
    boards.create_shot(pid, _shot(kept.id))

    boards.delete_scene(pid, doomed.id)

    assert [s.id for s in boards.list_scenes(pid)] == [kept.id]
    assert boards.list_shots(pid, doomed.id) == []
    assert len(boards.list_shots(pid, kept.id)) == 1
