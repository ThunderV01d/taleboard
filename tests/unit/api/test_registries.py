"""
Unit tests for the registry routes (characters, props and locations).

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), so no AWS calls are made.

Covers creating, reading, listing and editing entries in all three registries, their image URLs, the usage lookup, and the two kinds of delete.
"""
import pytest

from taleboard.schema.enums import Facing, Orientation
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, GroupLayer, PropLayer
from taleboard.schema.storyboard import Character, Location, Reference, Scene, Shot

REGISTRIES = ["characters", "props", "locations"]


@pytest.fixture
def pid(client):
    """
    The ID of a fresh project, created through the API.

    Arguments:
        client: TestClient - Client for the API.

    Returns:
        str - The project's ID.
    """
    return client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]


def _add(client, pid: str, registry: str, name: str, **fields) -> dict:
    """
    Creates a registry entry through the API.

    Arguments:
        client: TestClient - Client for the API.
        pid: str - The project's ID.
        registry: str - "characters", "props" or "locations".
        name: str - Name of the entry.
        fields: dict - Its other fields.

    Returns:
        dict - The created entry.
    """
    response = client.post(f"/projects/{pid}/{registry}", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def story(client, boards, pid):
    """
    A project with an office and a quay, Mara, a lamp, and two scenes in the office -- Mara and the lamp (in a group) in one shot, Mara alone in another.

    Arguments:
        client: TestClient - Client for the API.
        boards: StoryboardStore - The fake-backed store (scenes and shots have no routes yet).
        pid: str - The project's ID.

    Returns:
        dict - The project ID, and the scene.
    """
    for registry, name in [("locations", "Office"), ("locations", "Quay"), ("characters", "Mara"), ("props", "Lamp")]:
        _add(client, pid, registry, name)
    scene = Scene(name="Night watch", location_id="office")
    boards.create_scene(pid, scene)
    boards.create_shot(pid, Shot(scene_id=scene.id, order=0, layers=[BackgroundLayer(), GroupLayer(children=[CharacterLayer(character_id="mara"), PropLayer(prop_id="lamp")])]))
    boards.create_shot(pid, Shot(scene_id=scene.id, order=1, layers=[BackgroundLayer(), CharacterLayer(character_id="mara")]))
    return {"pid": pid, "scene": scene}


@pytest.mark.parametrize("registry", REGISTRIES)
def test_an_entry_is_created_with_an_id_from_its_name_and_can_be_read_and_listed(client, pid, registry):
    """
    Verifies that every registry creates an entry with a slugified ID (suffixed when taken), and returns it from reads and the list.

    Arguments:
        registry: str - "characters", "props" or "locations".
    """
    first = _add(client, pid, registry, "The Old Lamp", description="Brass, dented.")
    second = _add(client, pid, registry, "The Old Lamp")

    assert (first["id"], second["id"]) == ("the_old_lamp", "the_old_lamp_2")
    assert (first["name"], first["description"], first["image_urls"]) == ("The Old Lamp", "Brass, dented.", {})
    assert client.get(f"/projects/{pid}/{registry}/the_old_lamp").json() == first
    assert [e["id"] for e in client.get(f"/projects/{pid}/{registry}").json()] == ["the_old_lamp", "the_old_lamp_2"]


def test_the_three_registries_are_separate(client, pid):
    """
    Verifies that an entry appears only in its own registry.
    """
    _add(client, pid, "characters", "Mara")

    assert [e["id"] for e in client.get(f"/projects/{pid}/characters").json()] == ["mara"]
    assert client.get(f"/projects/{pid}/props").json() == []
    assert client.get(f"/projects/{pid}/locations").json() == []


def test_a_character_has_aliases_and_a_prop_does_not(client, pid):
    """
    Verifies that characters take aliases, while props simply have none.
    """
    mara = _add(client, pid, "characters", "Mara", aliases=["the keeper"])
    lamp = _add(client, pid, "props", "Lamp", aliases=["the light"])

    assert mara["aliases"] == ["the keeper"]
    assert "aliases" not in lamp


@pytest.mark.parametrize("registry", REGISTRIES)
@pytest.mark.parametrize("body", [{"name": ""}, {"name": "x" * 101}, {"name": "A", "description": "x" * 301}, {"description": "No name"}])
def test_an_invalid_entry_is_a_422_and_nothing_is_created(client, pid, registry, body):
    """
    Verifies that an empty, over-long or missing name, or an over-long description, is refused before anything is created.

    Arguments:
        registry: str - "characters", "props" or "locations".
        body: dict - An invalid request body.
    """
    assert client.post(f"/projects/{pid}/{registry}", json=body).status_code == 422
    assert client.get(f"/projects/{pid}/{registry}").json() == []


def test_the_client_cannot_choose_an_entrys_id_or_images(client, pid):
    """
    Verifies that an ID, references or plates in a create request are ignored -- IDs come from the name, images from generation and uploads.
    """
    mara = _add(client, pid, "characters", "Mara", id="someone_else", references={"left": {"image": "x.png", "source": "sketch"}})
    office = _add(client, pid, "locations", "Office", plates={"north": "x.png"})

    assert (mara["id"], mara["references"]) == ("mara", {})
    assert office["plates"] == {}


def test_editing_changes_only_what_was_sent_and_never_the_id(client, pid):
    """
    Verifies that PATCH changes the fields sent, leaves the rest (and the ID) alone, and that renaming keeps the original ID.
    """
    _add(client, pid, "characters", "Mara", description="A wiry woman.", aliases=["the keeper"])

    renamed = client.patch(f"/projects/{pid}/characters/mara", json={"name": "Mara Voss"}).json()
    described = client.patch(f"/projects/{pid}/characters/mara", json={"description": "A wiry woman in an oilskin coat."}).json()

    assert (renamed["id"], renamed["name"], renamed["description"], renamed["aliases"]) == ("mara", "Mara Voss", "A wiry woman.", ["the keeper"])
    assert (described["name"], described["description"]) == ("Mara Voss", "A wiry woman in an oilskin coat.")
    assert client.patch(f"/projects/{pid}/characters/mara", json={"aliases": ["Voss"]}).json()["aliases"] == ["Voss"]
    assert client.patch(f"/projects/{pid}/characters/mara", json={"name": None}).json()["name"] == "Mara Voss"  # null means "unchanged"


def test_editing_keeps_an_entrys_images(client, boards, pid):
    """
    Verifies that editing an entry's text never touches its reference images.
    """
    _add(client, pid, "characters", "Mara")
    mara = boards.get_entry(pid, Character, "mara")
    mara.references[Orientation.LEFT] = Reference(image=f"projects/{pid}/refs/mara-left.png", source="sketch")
    boards.save_entry(pid, mara)

    edited = client.patch(f"/projects/{pid}/characters/mara", json={"description": "New."}).json()

    assert edited["references"] == {"left": {"image": f"projects/{pid}/refs/mara-left.png", "source": "sketch"}}


def test_an_invalid_edit_is_a_422_and_changes_nothing(client, pid):
    """
    Verifies that an edit breaking the limits is refused and leaves the entry as it was.
    """
    _add(client, pid, "props", "Lamp")

    assert client.patch(f"/projects/{pid}/props/lamp", json={"name": ""}).status_code == 422
    assert client.patch(f"/projects/{pid}/props/lamp", json={"description": "x" * 301}).status_code == 422
    assert client.get(f"/projects/{pid}/props/lamp").json()["name"] == "Lamp"


def test_image_urls_are_given_for_the_projects_own_images_only(client, boards, pid):
    """
    Verifies that every reference and plate gets a download URL -- except a key pointing outside the project, which is never signed.
    """
    _add(client, pid, "characters", "Mara")
    _add(client, pid, "locations", "Office")
    mara = boards.get_entry(pid, Character, "mara")
    own, foreign = f"projects/{pid}/refs/mara-left.png", "projects/someone-else/refs/secret.png"
    mara.references[Orientation.LEFT] = Reference(image=own, source="generated")
    mara.references[Orientation.RIGHT] = Reference(image=foreign, source="generated")
    boards.save_entry(pid, mara)
    office = boards.get_entry(pid, Location, "office")
    office.plates[Facing.NORTH] = f"projects/{pid}/plates/office-n.png"
    boards.save_entry(pid, office)

    urls = client.get(f"/projects/{pid}/characters/mara").json()["image_urls"]
    plate_urls = client.get(f"/projects/{pid}/locations").json()[0]["image_urls"]

    assert set(urls) == {own}
    assert urls[own].startswith("https://")
    assert set(plate_urls) == {f"projects/{pid}/plates/office-n.png"}


@pytest.mark.parametrize("method, suffix, body", [("get", "", None), ("patch", "", {"name": "X"}), ("get", "/usage", None), ("delete", "", None)])
def test_an_unknown_entry_is_a_404(client, pid, method, suffix, body):
    """
    Verifies that every route naming an entry answers 404 when it doesn't exist.

    Arguments:
        method: str - HTTP method.
        suffix: str - Path after the entry ID.
        body: dict - Request body, if the route takes one.
    """
    response = client.request(method, f"/projects/{pid}/characters/nobody{suffix}", json=body)

    assert response.status_code == 404
    assert "nobody" in response.json()["detail"]


@pytest.mark.parametrize("registry", REGISTRIES)
def test_an_unknown_project_is_a_404_for_every_registry(client, registry):
    """
    Verifies that the registries 404 for a project that doesn't exist.

    Arguments:
        registry: str - "characters", "props" or "locations".
    """
    assert client.get(f"/projects/nope/{registry}").status_code == 404
    assert client.post(f"/projects/nope/{registry}", json={"name": "Mara"}).status_code == 404


def test_usage_lists_the_scenes_and_shots_using_an_entry(client, story):
    """
    Verifies that the usage route lists where a character, prop or location is used -- what the delete popup shows.
    """
    pid, scene = story["pid"], story["scene"]

    mara = client.get(f"/projects/{pid}/characters/mara/usage").json()
    lamp = client.get(f"/projects/{pid}/props/lamp/usage").json()
    quay = client.get(f"/projects/{pid}/locations/quay/usage").json()

    assert mara == {"scenes": [{"scene_id": scene.id, "name": "Night watch", "order": 0, "shots": [{"shot_id": mara["scenes"][0]["shots"][0]["shot_id"], "order": 0}, {"shot_id": mara["scenes"][0]["shots"][1]["shot_id"], "order": 1}]}]}
    assert [s["order"] for s in lamp["scenes"][0]["shots"]] == [0]
    assert quay == {"scenes": []}


def test_deleting_a_character_removes_their_layers_and_returns_what_was_removed(client, boards, story):
    """
    Verifies that deleting a character answers with where they were used, and leaves no layer showing them.
    """
    pid, scene = story["pid"], story["scene"]

    removed = client.delete(f"/projects/{pid}/characters/mara")

    assert removed.status_code == 200
    assert [s["order"] for s in removed.json()["scenes"][0]["shots"]] == [0, 1]
    assert client.get(f"/projects/{pid}/characters/mara").status_code == 404
    assert not any(isinstance(layer, CharacterLayer) for shot in boards.list_shots(pid, scene.id) for layer in shot.all_layers())


def test_deleting_a_location_needs_exactly_one_choice(client, story):
    """
    Verifies that a location delete with neither choice, or both, is a 400 -- and deletes nothing.
    """
    pid = story["pid"]

    neither = client.delete(f"/projects/{pid}/locations/office")
    both = client.delete(f"/projects/{pid}/locations/office", params={"move_scenes_to": "quay", "delete_scenes": "true"})

    assert (neither.status_code, both.status_code) == (400, 400)
    assert "move_scenes_to" in neither.json()["detail"]
    assert client.get(f"/projects/{pid}/locations/office").status_code == 200


def test_deleting_a_location_can_move_its_scenes(client, boards, story):
    """
    Verifies that move_scenes_to moves the location's scenes (keeping their shots) and deletes the location.
    """
    pid, scene = story["pid"], story["scene"]

    moved = client.delete(f"/projects/{pid}/locations/office", params={"move_scenes_to": "quay"})

    assert moved.status_code == 200
    assert [s["scene_id"] for s in moved.json()["scenes"]] == [scene.id]
    assert boards.get_scene(pid, scene.id).location_id == "quay"
    assert len(boards.list_shots(pid, scene.id)) == 2
    assert client.get(f"/projects/{pid}/locations/office").status_code == 404


def test_deleting_a_location_can_delete_its_scenes(client, boards, story):
    """
    Verifies that delete_scenes=true deletes the location's scenes and their shots, and the location.
    """
    pid, scene = story["pid"], story["scene"]

    deleted = client.delete(f"/projects/{pid}/locations/office", params={"delete_scenes": "true"})

    assert deleted.status_code == 200
    assert boards.list_scenes(pid) == []
    assert boards.list_shots(pid, scene.id) == []


@pytest.mark.parametrize("destination", ["office", "nowhere"])
def test_moving_scenes_to_the_same_or_a_missing_location_is_a_400(client, boards, story, destination):
    """
    Verifies that a bad destination is a 400 (the request is wrong), not a 404 -- and that nothing is moved or deleted.

    Arguments:
        destination: str - An invalid location to move the scenes to.
    """
    pid, scene = story["pid"], story["scene"]

    response = client.delete(f"/projects/{pid}/locations/office", params={"move_scenes_to": destination})

    assert response.status_code == 400
    assert boards.get_scene(pid, scene.id).location_id == "office"


def test_deleting_an_unknown_location_is_a_404(client, pid):
    """
    Verifies that deleting a location that doesn't exist is a 404, once a choice has been made.
    """
    assert client.delete(f"/projects/{pid}/locations/nowhere", params={"delete_scenes": "true"}).status_code == 404
