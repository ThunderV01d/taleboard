"""
Unit tests for cascades.

Runs against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py), so no AWS calls are made.

Covers finding where a registry entry is used, deleting a character or prop along with every layer showing it (groups and concurrent edits included), and deleting a location by moving or deleting its scenes.
"""
import pytest

from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Prop, Scene, Shot
from taleboard.storage import cascades
from taleboard.storage.cascades import delete_entry_and_uses, delete_location, find_usage
from taleboard.storage.storyboard_store import ShotConflictError, StoryboardStore


@pytest.fixture
def boards(aws):
    """
    A StoryboardStore backed by the shared fakes.

    Arguments:
        aws: None - The shared fakes (they set the TALEBOARD_* environment variables).

    Returns:
        StoryboardStore - A store backed by the fakes.
    """
    return StoryboardStore.from_env()


@pytest.fixture
def story(boards):
    """
    A project with two locations, a character, a prop, and three scenes:

        scene 0 (office):  shot 0 -- Mara;  shot 1 -- Mara, in a group with the lamp;  shot 2 -- background only
        scene 1 (quay):    shot 0 -- Mara and the lamp
        scene 2 (office):  no shots yet

    Arguments:
        boards: StoryboardStore - The fake-backed store.

    Returns:
        dict - The project ID, and the scenes and shots by name.
    """
    pid = boards.create_project("Lighthouse", "mara-user").project_id
    for model, name in [(Location, "Office"), (Location, "Quay"), (Character, "Mara"), (Prop, "Lamp")]:
        boards.create_entry(pid, model, name)
    office, quay, empty = Scene(name="Office", order=0, location_id="office"), Scene(name="Quay", order=1, location_id="quay"), Scene(name="Later", order=2, location_id="office")
    for scene in (office, quay, empty):
        boards.create_scene(pid, scene)
    shots = {
        "office_0": Shot(scene_id=office.id, order=0, layers=[BackgroundLayer(), CharacterLayer(character_id="mara")]),
        "office_1": Shot(scene_id=office.id, order=1, layers=[BackgroundLayer(), GroupLayer(children=[CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")]), TextLayer(text="Hi")]),
        "office_2": Shot(scene_id=office.id, order=2, layers=[BackgroundLayer()]),
        "quay_0": Shot(scene_id=quay.id, order=0, layers=[BackgroundLayer(), CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")]),
    }
    for shot in shots.values():
        boards.create_shot(pid, shot)
    return {"pid": pid, "office": office, "quay": quay, "empty": empty, **shots}


def _layer_types(shot: Shot) -> list[str]:
    """
    Lists a shot's top-level layer types, with each group's children's types in brackets.

    Arguments:
        shot: Shot - The shot.

    Returns:
        list[str] - The layer types.
    """
    return [f"group{[type(c).__name__ for c in l.children]}" if isinstance(l, GroupLayer) else type(l).__name__ for l in shot.layers]


def test_list_all_shots_finds_every_scenes_shots(boards, story):
    """
    Verifies that list_all_shots returns every shot in the project, grouped by scene and in order within each.
    """
    shots = boards.list_all_shots(story["pid"])

    assert len(shots) == 4
    by_scene = [s.order for s in shots if s.scene_id == story["office"].id]
    assert by_scene == [0, 1, 2]


def test_a_characters_usage_lists_each_scene_and_shot_it_appears_in_including_inside_groups(boards, story):
    """
    Verifies that a character's usage names every scene and shot showing them -- a layer nested in a group counts -- in story order, and leaves out scenes they're not in.
    """
    usage = find_usage(boards, story["pid"], Character, "mara")

    assert [(scene.name, [shot.order for shot in scene.shots]) for scene in usage.scenes] == [("Office", [0, 1]), ("Quay", [0])]
    assert usage.shot_count == 3


def test_a_locations_usage_lists_its_scenes_even_one_with_no_shots(boards, story):
    """
    Verifies that a location's usage is every scene set there, with all their shots -- and includes a scene that has no shots yet.
    """
    usage = find_usage(boards, story["pid"], Location, "office")

    assert [(scene.name, [shot.order for shot in scene.shots]) for scene in usage.scenes] == [("Office", [0, 1, 2]), ("Later", [])]


def test_an_unused_entry_has_no_usage(boards, story):
    """
    Verifies that an entry nothing uses has an empty usage.
    """
    boards.create_entry(story["pid"], Prop, "Rope")

    usage = find_usage(boards, story["pid"], Prop, "rope")

    assert (usage.scenes, usage.shot_count) == ([], 0)


def test_deleting_a_character_removes_their_layers_everywhere_and_then_them(boards, story):
    """
    Verifies that deleting a character removes every layer showing them (inside groups too), leaves every other layer alone, and deletes the character last.
    """
    pid = story["pid"]

    removed = delete_entry_and_uses(boards, pid, Character, "mara")

    assert removed.shot_count == 3
    assert _layer_types(boards.get_shot(pid, story["office"].id, story["office_0"].id)) == ["BackgroundLayer"]
    assert _layer_types(boards.get_shot(pid, story["office"].id, story["office_1"].id)) == ["BackgroundLayer", "group['PropLayer']", "TextLayer"]
    assert _layer_types(boards.get_shot(pid, story["quay"].id, story["quay_0"].id)) == ["BackgroundLayer", "PropLayer"]
    with pytest.raises(KeyError):
        boards.get_entry(pid, Character, "mara")
    assert find_usage(boards, pid, Character, "mara").scenes == []


def test_a_group_emptied_by_a_deletion_goes_with_it_but_an_already_empty_one_stays(boards, story):
    """
    Verifies that a group left with nothing in it by a deletion is removed too, while a group that was already empty is kept.
    """
    pid, scene = story["pid"], story["office"]
    shot = Shot(scene_id=scene.id, order=3, layers=[GroupLayer(name="held", children=[PropLayer(prop_id="lamp")]), GroupLayer(name="empty")])
    boards.create_shot(pid, shot)

    delete_entry_and_uses(boards, pid, Prop, "lamp")

    assert [layer.name for layer in boards.get_shot(pid, scene.id, shot.id).layers] == ["empty"]


def test_each_edited_shot_is_saved_with_the_version_check(boards, story):
    """
    Verifies that removing layers goes through the normal versioned save, so every edited shot's version moves on.
    """
    pid = story["pid"]

    delete_entry_and_uses(boards, pid, Prop, "lamp")

    assert boards.get_shot(pid, story["office"].id, story["office_1"].id).version == 1
    assert boards.get_shot(pid, story["office"].id, story["office_0"].id).version == 0  # Didn't use the lamp, so untouched


def test_a_shot_edited_mid_deletion_keeps_the_other_edit(boards, story, monkeypatch):
    """
    Verifies that if someone saves a shot between the deletion loading and saving it, the deletion reloads and applies itself to their version -- their edit survives, and the layers still go.
    """
    pid, scene, shot = story["pid"], story["quay"], story["quay_0"]
    real_save = boards.save_shot
    interrupted = {"done": False}

    def save_after_someone_else(project_id, edited):
        """
        Lets another editor save this test's shot first (once), then saves as normal.
        """
        if edited.id == shot.id and not interrupted["done"]:
            interrupted["done"] = True
            theirs = boards.get_shot(project_id, edited.scene_id, edited.id)
            real_save(project_id, theirs.model_copy(update={"description": "their edit"}))
        return real_save(project_id, edited)

    monkeypatch.setattr(boards, "save_shot", save_after_someone_else)

    delete_entry_and_uses(boards, pid, Character, "mara")

    saved = boards.get_shot(pid, scene.id, shot.id)
    assert saved.description == "their edit"
    assert _layer_types(saved) == ["BackgroundLayer", "PropLayer"]


def test_a_shot_that_keeps_conflicting_gives_up_after_a_few_attempts(boards, story, monkeypatch):
    """
    Verifies that the deletion doesn't retry forever: after SAVE_ATTEMPTS conflicts it raises, and the character is not deleted.
    """
    pid = story["pid"]

    def always_conflicts(project_id, edited):
        """
        Refuses every save, as if someone always got there first.
        """
        raise ShotConflictError(edited.id, edited.version + 1)

    monkeypatch.setattr(boards, "save_shot", always_conflicts)

    with pytest.raises(ShotConflictError):
        delete_entry_and_uses(boards, pid, Character, "mara")
    assert boards.get_entry(pid, Character, "mara").name == "Mara"  # Layers go first, the entry last -- so it's still there


def test_deleting_a_missing_entry_is_a_key_error(boards, story):
    """
    Verifies that deleting a character that doesn't exist raises a KeyError and changes nothing.
    """
    with pytest.raises(KeyError):
        delete_entry_and_uses(boards, story["pid"], Character, "nobody")


def test_a_location_cant_be_deleted_as_if_it_were_a_character(boards, story):
    """
    Verifies that delete_entry_and_uses refuses a location, which needs a decision about its scenes.
    """
    with pytest.raises(ValueError, match="delete_location"):
        delete_entry_and_uses(boards, story["pid"], Location, "office")
    assert boards.get_entry(story["pid"], Location, "office").name == "Office"


def test_deleting_a_location_can_move_its_scenes_elsewhere(boards, story):
    """
    Verifies that moving a deleted location's scenes keeps them and their shots, now set in the other location, and leaves its backgrounds needing regeneration.
    """
    pid, office = story["pid"], story["office"]
    shot = boards.get_shot(pid, office.id, story["office_0"].id)
    background = shot.layers[0]
    background.last_generated_params = background.current_params(shot.generation_context(office))
    shot = boards.save_shot(pid, shot)

    moved = delete_location(boards, pid, "office", move_scenes_to="quay")

    assert [scene.name for scene in moved.scenes] == ["Office", "Later"]
    assert [scene.location_id for scene in boards.list_scenes(pid)] == ["quay", "quay", "quay"]
    assert len(boards.list_shots(pid, office.id)) == 3
    reloaded = boards.get_shot(pid, office.id, shot.id)
    assert reloaded.layers[0].needs_regeneration(reloaded.generation_context(boards.get_scene(pid, office.id))) is True
    with pytest.raises(KeyError):
        boards.get_entry(pid, Location, "office")


def test_deleting_a_location_can_delete_its_scenes_and_their_shots(boards, story):
    """
    Verifies that deleting a location's scenes removes them and all their shots, and leaves other locations' scenes alone.
    """
    pid = story["pid"]

    deleted = delete_location(boards, pid, "office", move_scenes_to=None)

    assert [scene.name for scene in deleted.scenes] == ["Office", "Later"]
    assert [scene.name for scene in boards.list_scenes(pid)] == ["Quay"]
    assert boards.list_shots(pid, story["office"].id) == []
    assert len(boards.list_shots(pid, story["quay"].id)) == 1


def test_deleting_a_location_requires_a_choice(boards, story):
    """
    Verifies that the move-or-delete choice can't be left out -- forgetting it is an error, never a silent deletion.
    """
    with pytest.raises(TypeError):
        delete_location(boards, story["pid"], "office")
    assert len(boards.list_scenes(story["pid"])) == 3


@pytest.mark.parametrize("destination", ["office", "nowhere"])
def test_moving_scenes_to_the_same_or_a_missing_location_is_refused_before_anything_changes(boards, story, destination):
    """
    Verifies that moving a location's scenes onto itself, or to a location that doesn't exist, is a ValueError -- and that nothing has been moved or deleted.

    Arguments:
        destination: str - An invalid location to move the scenes to.
    """
    pid = story["pid"]

    with pytest.raises(ValueError):
        delete_location(boards, pid, "office", move_scenes_to=destination)

    assert [scene.location_id for scene in boards.list_scenes(pid)] == ["office", "quay", "office"]
    assert boards.get_entry(pid, Location, "office").name == "Office"


def test_deleting_a_missing_location_is_a_key_error(boards, story):
    """
    Verifies that deleting a location that doesn't exist raises a KeyError, whichever choice is made.
    """
    with pytest.raises(KeyError):
        delete_location(boards, story["pid"], "nowhere", move_scenes_to=None)


def test_deleting_a_project_removes_every_item_and_every_image(boards, story):
    """
    Verifies that delete_project removes the project's metadata, registries, scenes and shots, and everything under its S3 prefix -- and nothing of another project's.
    """
    pid = story["pid"]
    other = boards.create_project("Other", "mara-user").project_id
    for project_id in (pid, other):
        for name in ("a.png", "b/c.png"):
            boards._s3.put_object(Bucket=boards._bucket, Key=f"projects/{project_id}/{name}", Body=b"png")

    boards.delete_project(pid)

    with pytest.raises(KeyError):
        boards.get_project(pid)
    assert boards._query(pid) == []
    assert "Contents" not in boards._s3.list_objects_v2(Bucket=boards._bucket, Prefix=f"projects/{pid}/")
    assert boards.get_project(other).name == "Other"
    assert len(boards._s3.list_objects_v2(Bucket=boards._bucket, Prefix=f"projects/{other}/")["Contents"]) == 2
