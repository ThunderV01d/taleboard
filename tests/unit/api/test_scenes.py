"""
Unit tests for the scene routes.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), so no AWS calls are made.

Covers creating scenes in a location that must exist, reading, listing and editing them, reordering them, and deleting them with their shots.
"""
import pytest

from taleboard.schema.storyboard import Shot


@pytest.fixture
def pid(client):
    """
    The ID of a fresh project with an office and a quay, created through the API.

    Arguments:
        client: TestClient - Client for the API.

    Returns:
        str - The project's ID.
    """
    pid = client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]
    for name in ("Office", "Quay"):
        assert client.post(f"/projects/{pid}/locations", json={"name": name}).status_code == 201
    return pid


def _add(client, pid: str, name: str = "Night watch", **fields) -> dict:
    """
    Creates a scene in the office through the API.

    Arguments:
        client: TestClient - Client for the API.
        pid: str - The project's ID.
        name: str - Name of the scene. Defaults to "Night watch".
        fields: dict - Its other fields.

    Returns:
        dict - The created scene.
    """
    response = client.post(f"/projects/{pid}/scenes", json={"name": name, "location_id": "office", **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_scene_is_created_on_a_clear_day_and_can_be_read_and_listed(client, pid):
    """
    Verifies that a created scene gets an ID, the first position and a clear-day default, and comes back from reads and the list.
    """
    scene = _add(client, pid, description="Mara keeps the lamp lit.")

    assert (scene["order"], scene["location_id"], scene["time_of_day"], scene["atmosphere"]) == (0, "office", "day", "clear")
    assert client.get(f"/projects/{pid}/scenes/{scene['id']}").json() == scene
    assert client.get(f"/projects/{pid}/scenes").json() == [scene]


def test_a_scene_can_be_created_with_its_lighting(client, pid):
    """
    Verifies that time of day and atmosphere can be set on create, and that unknown values are refused.
    """
    scene = _add(client, pid, time_of_day="night", atmosphere="stormy")

    assert (scene["time_of_day"], scene["atmosphere"]) == ("night", "stormy")
    assert client.post(f"/projects/{pid}/scenes", json={"location_id": "office", "time_of_day": "midnight"}).status_code == 422
    assert client.post(f"/projects/{pid}/scenes", json={"location_id": "office", "atmosphere": "sunny"}).status_code == 422


def test_new_scenes_go_at_the_end_even_after_a_deletion(client, pid):
    """
    Verifies that each new scene is placed after the last one -- and that deleting one in the middle doesn't make the next new scene share a position.
    """
    first, middle, last = (_add(client, pid, name) for name in ("One", "Two", "Three"))
    assert [first["order"], middle["order"], last["order"]] == [0, 1, 2]

    client.delete(f"/projects/{pid}/scenes/{middle['id']}")
    added = _add(client, pid, "Four")

    assert added["order"] == 3
    assert [s["name"] for s in client.get(f"/projects/{pid}/scenes").json()] == ["One", "Three", "Four"]


def test_a_scene_needs_a_location_that_exists(client, pid):
    """
    Verifies that a scene without a location is a 422, and one in a location that isn't in the registry is a 400 -- neither is created.
    """
    assert client.post(f"/projects/{pid}/scenes", json={"name": "Nowhere"}).status_code == 422

    missing = client.post(f"/projects/{pid}/scenes", json={"name": "Nowhere", "location_id": "moon"})

    assert missing.status_code == 400
    assert "moon" in missing.json()["detail"]
    assert client.get(f"/projects/{pid}/scenes").json() == []


@pytest.mark.parametrize("body", [{"name": "x" * 101}, {"description": "x" * 2001}])
def test_scene_names_and_descriptions_are_capped(client, pid, body):
    """
    Verifies that an over-long name or description is refused on create and on edit.

    Arguments:
        body: dict - An over-long field.
    """
    scene = _add(client, pid)

    assert client.post(f"/projects/{pid}/scenes", json={"location_id": "office", **body}).status_code == 422
    assert client.patch(f"/projects/{pid}/scenes/{scene['id']}", json=body).status_code == 422


def test_editing_a_scene_changes_only_the_fields_sent(client, pid):
    """
    Verifies that PATCH changes the fields sent and keeps the rest, ID and position included.
    """
    scene = _add(client, pid, description="Mara keeps the lamp lit.")

    edited = client.patch(f"/projects/{pid}/scenes/{scene['id']}", json={"time_of_day": "dusk", "atmosphere": "foggy"})

    assert edited.status_code == 200
    assert edited.json() == {**scene, "time_of_day": "dusk", "atmosphere": "foggy"}
    assert client.get(f"/projects/{pid}/scenes/{scene['id']}").json() == edited.json()


def test_a_scene_can_move_only_to_a_location_that_exists(client, pid):
    """
    Verifies that a scene can be moved to another registered location, and that a move to a missing one is a 400 that changes nothing.
    """
    scene = _add(client, pid)

    moved = client.patch(f"/projects/{pid}/scenes/{scene['id']}", json={"location_id": "quay"})
    refused = client.patch(f"/projects/{pid}/scenes/{scene['id']}", json={"location_id": "moon", "name": "Lost"})

    assert moved.json()["location_id"] == "quay"
    assert refused.status_code == 400
    assert client.get(f"/projects/{pid}/scenes/{scene['id']}").json() == moved.json()


def test_editing_a_scene_leaves_its_shots_alone(client, boards, pid):
    """
    Verifies that changing a scene's lighting doesn't rewrite its shots -- their backgrounds go out of date by comparison, not by being edited.
    """
    scene = _add(client, pid)
    shot = Shot(scene_id=scene["id"], order=0)
    boards.create_shot(pid, shot)

    client.patch(f"/projects/{pid}/scenes/{scene['id']}", json={"time_of_day": "night"})

    assert boards.get_shot(pid, scene["id"], shot.id) == shot


def test_scenes_are_reordered_from_the_full_list_of_their_ids(client, pid):
    """
    Verifies that PUT /order renumbers the scenes from 0 in the order given, and the list then follows it.
    """
    one, two, three = (_add(client, pid, name) for name in ("One", "Two", "Three"))

    reordered = client.put(f"/projects/{pid}/scenes/order", json={"scene_ids": [three["id"], one["id"], two["id"]]})

    assert reordered.status_code == 200
    assert [(s["name"], s["order"]) for s in reordered.json()] == [("Three", 0), ("One", 1), ("Two", 2)]
    assert client.get(f"/projects/{pid}/scenes").json() == reordered.json()


def test_reordering_closes_gaps_left_by_deletions(client, pid):
    """
    Verifies that reordering into the same order still renumbers the scenes 0, 1, 2 after a deletion left a gap.
    """
    one, two, three = (_add(client, pid, name) for name in ("One", "Two", "Three"))
    client.delete(f"/projects/{pid}/scenes/{two['id']}")

    reordered = client.put(f"/projects/{pid}/scenes/order", json={"scene_ids": [one["id"], three["id"]]})

    assert [s["order"] for s in reordered.json()] == [0, 1]


@pytest.mark.parametrize("ids", [
    lambda one, two: [one],                    # Missing a scene
    lambda one, two: [one, two, "extra"],      # A scene that isn't in the project
    lambda one, two: [one, one],               # A repeat, standing in for the missing one
    lambda one, two: [one, two, two],          # A repeat on top of the full list
    lambda one, two: [],
])
def test_a_reorder_must_list_every_scene_exactly_once(client, pid, ids):
    """
    Verifies that a missing, extra or repeated scene ID is a 400 that leaves the order alone.

    Arguments:
        ids: Callable - Builds the invalid list from the two scenes' IDs.
    """
    one, two = _add(client, pid, "One"), _add(client, pid, "Two")

    response = client.put(f"/projects/{pid}/scenes/order", json={"scene_ids": ids(one["id"], two["id"])})

    assert response.status_code == 400
    assert [s["name"] for s in client.get(f"/projects/{pid}/scenes").json()] == ["One", "Two"]


def test_reordering_an_empty_project_is_fine(client, pid):
    """
    Verifies that an empty list reorders a project with no scenes, rather than being refused.
    """
    response = client.put(f"/projects/{pid}/scenes/order", json={"scene_ids": []})

    assert (response.status_code, response.json()) == (200, [])


def test_a_deleted_scene_takes_its_shots_with_it(client, boards, pid):
    """
    Verifies that DELETE answers 204 with no body, and removes the scene and its shots but not other scenes' shots.
    """
    doomed, kept = _add(client, pid, "Doomed"), _add(client, pid, "Kept")
    for scene in (doomed, kept):
        boards.create_shot(pid, Shot(scene_id=scene["id"], order=0))

    deleted = client.delete(f"/projects/{pid}/scenes/{doomed['id']}")

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert client.get(f"/projects/{pid}/scenes/{doomed['id']}").status_code == 404
    assert [shot.scene_id for shot in boards.list_all_shots(pid)] == [kept["id"]]


@pytest.mark.parametrize("method, body", [("get", None), ("patch", {"name": "New"}), ("delete", None)])
def test_an_unknown_scene_is_a_404(client, pid, method, body):
    """
    Verifies that every route naming a scene answers 404, with a message, when it doesn't exist.

    Arguments:
        method: str - HTTP method.
        body: dict - Request body, if the route takes one.
    """
    response = client.request(method, f"/projects/{pid}/scenes/does-not-exist", json=body)

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


@pytest.mark.parametrize("method, path, body", [
    ("get", "", None), ("post", "", {"location_id": "office"}), ("put", "/order", {"scene_ids": []}), ("get", "/s", None),
])
def test_scenes_in_an_unknown_project_are_a_404(client, method, path, body):
    """
    Verifies that the scene routes answer 404 for a project that doesn't exist.

    Arguments:
        method: str - HTTP method.
        path: str - Path after /scenes.
        body: dict - Request body, if the route takes one.
    """
    assert client.request(method, f"/projects/does-not-exist/scenes{path}", json=body).status_code == 404
