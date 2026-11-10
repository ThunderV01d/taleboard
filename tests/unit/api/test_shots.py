"""
Unit tests for the shot routes.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), so no AWS calls are made.

Covers creating shots with a starting background, reading and listing them with their image URLs and what's out of date, saving them (layer validation, registry checks and the version check), reordering them, and deleting them.
"""
import pytest

from taleboard.generation.planning import Registry


@pytest.fixture
def scene(client):
    """
    A fresh project with an office, Mara and a lamp, and one scene in the office -- all created through the API.

    Arguments:
        client: TestClient - Client for the API.

    Returns:
        dict - The project ID ("pid"), the scene's ID ("id"), and the scene's shots URL ("shots").
    """
    pid = client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]
    for registry, name in [("locations", "Office"), ("characters", "Mara"), ("props", "Lamp")]:
        assert client.post(f"/projects/{pid}/{registry}", json={"name": name}).status_code == 201
    scene_id = client.post(f"/projects/{pid}/scenes", json={"location_id": "office"}).json()["id"]
    return {"pid": pid, "id": scene_id, "shots": f"/projects/{pid}/scenes/{scene_id}/shots"}


def _add(client, scene: dict, **fields) -> dict:
    """
    Creates a shot through the API.

    Arguments:
        client: TestClient - Client for the API.
        scene: dict - The scene fixture.
        fields: dict - The shot's fields.

    Returns:
        dict - The created shot.
    """
    response = client.post(scene["shots"], json=fields)
    assert response.status_code == 201, response.text
    return response.json()


def _save(client, scene: dict, shot: dict, **changes):
    """
    Saves a shot through the API, sending its editable fields with any changes.

    Arguments:
        client: TestClient - Client for the API.
        scene: dict - The scene fixture.
        shot: dict - The shot as last read.
        changes: dict - Fields to change.

    Returns:
        Response - The API's response.
    """
    editable = ("description", "duration_s", "shot_size", "angle", "details", "layers", "version")
    return client.put(f"{scene['shots']}/{shot['id']}", json={**{key: shot[key] for key in editable}, **changes})


def test_a_new_shot_starts_with_an_ungenerated_background(client, scene):
    """
    Verifies that a created shot belongs to its scene, starts at version 0, and holds one background layer that hasn't been generated.
    """
    shot = _add(client, scene, description="Mara climbs the stairs.", shot_size="wide")

    assert (shot["scene_id"], shot["order"], shot["version"], shot["shot_size"]) == (scene["id"], 0, 0, "wide")
    assert [(layer["type"], layer["image"], layer["last_generated_params"]) for layer in shot["layers"]] == [("background", None, None)]
    assert shot["image_urls"] == {}
    assert client.get(f"{scene['shots']}/{shot['id']}").json() == shot
    assert client.get(scene["shots"]).json() == [shot]


def test_new_shots_go_at_the_end_even_after_a_deletion(client, scene):
    """
    Verifies that each new shot is placed after the last one, even when a deletion left a gap.
    """
    first, middle, _ = (_add(client, scene) for _ in range(3))
    client.delete(f"{scene['shots']}/{middle['id']}")

    assert _add(client, scene)["order"] == 3
    assert [s["order"] for s in client.get(scene["shots"]).json()] == [0, 2, 3]


@pytest.mark.parametrize("body", [{"duration_s": 0}, {"duration_s": 61}, {"details": "x" * 151}, {"shot_size": "extreme_close_up"}, {"angle": "sideways"}])
def test_a_shot_with_invalid_framing_is_refused(client, scene, body):
    """
    Verifies that a bad duration, over-long details or an unknown size or angle is a 422 on create, and nothing is created.

    Arguments:
        body: dict - An invalid field.
    """
    assert client.post(scene["shots"], json=body).status_code == 422
    assert client.get(scene["shots"]).json() == []


def test_saving_replaces_the_layers_and_bumps_the_version(client, scene):
    """
    Verifies that a save stores the new framing and layer tree (groups included), keeps the shot's ID, scene and position, and returns version + 1.
    """
    shot = _add(client, scene)
    layers = shot["layers"] + [
        {"type": "group", "name": "Mara and lamp", "children": [{"type": "character", "character_id": "mara", "action": "waving"}, {"type": "prop", "prop_id": "lamp"}]},
        {"type": "text", "text": "Later...", "transform": {"x": 100, "y": 50}},
    ]

    saved = _save(client, scene, shot, layers=layers, shot_size="close_up")

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["id"], body["scene_id"], body["order"], body["version"], body["shot_size"]) == (shot["id"], scene["id"], 0, 1, "close_up")
    assert [layer["type"] for layer in body["layers"]] == ["background", "group", "text"]
    assert [child["type"] for child in body["layers"][1]["children"]] == ["character", "prop"]
    assert client.get(f"{scene['shots']}/{shot['id']}").json() == body


def test_a_save_from_an_out_of_date_copy_is_a_409_with_the_current_version(client, scene):
    """
    Verifies the version check end to end: two editors load version 0, the first save wins, and the second is refused with the version to reload.
    """
    shot = _add(client, scene)
    assert _save(client, scene, shot, description="First editor").status_code == 200

    stale = _save(client, scene, shot, description="Second editor")

    assert stale.status_code == 409
    assert stale.json()["current_version"] == 1
    assert client.get(f"{scene['shots']}/{shot['id']}").json()["description"] == "First editor"


def test_saving_again_from_the_returned_version_works(client, scene):
    """
    Verifies that an editor which keeps the shot each save returns can save repeatedly without conflicts.
    """
    shot = _add(client, scene)
    for text in ("one", "two", "three"):
        shot = _save(client, scene, shot, description=text).json()

    assert (shot["version"], shot["description"]) == (3, "three")


def test_a_save_must_carry_a_version(client, scene):
    """
    Verifies that a save without a version (which could otherwise overwrite anything) is a 422.
    """
    shot = _add(client, scene)

    response = client.put(f"{scene['shots']}/{shot['id']}", json={"layers": []})

    assert response.status_code == 422


def test_two_layers_with_the_same_id_are_a_422(client, scene):
    """
    Verifies that a save whose layer tree repeats an ID is refused like any other bad body -- a 422 naming the problem, not a server error.
    """
    shot = _add(client, scene)
    layers = [{"type": "text", "id": "a"}, {"type": "group", "children": [{"type": "image", "id": "a"}]}]

    response = _save(client, scene, shot, layers=layers)

    assert response.status_code == 422
    assert "same id" in response.text
    assert client.get(f"{scene['shots']}/{shot['id']}").json()["version"] == 0


@pytest.mark.parametrize("layer", [{"type": "camera"}, {"type": "character"}, {"type": "text", "opacity": 2}])
def test_an_invalid_layer_is_a_422(client, scene, layer):
    """
    Verifies that an unknown layer type, a character without a character_id, or an out-of-range value is refused.

    Arguments:
        layer: dict - An invalid layer.
    """
    shot = _add(client, scene)

    assert _save(client, scene, shot, layers=[layer]).status_code == 422


@pytest.mark.parametrize("layer, missing", [
    ({"type": "character", "character_id": "ghost"}, "ghost"),
    ({"type": "group", "children": [{"type": "prop", "prop_id": "anchor"}]}, "anchor"),
])
def test_a_shot_can_only_show_characters_and_props_in_the_registries(client, scene, layer, missing):
    """
    Verifies that a save showing a character or prop that isn't registered -- even inside a group -- is a 400 naming it, and changes nothing.

    Arguments:
        layer: dict - A layer showing something unregistered.
        missing: str - Its ID.
    """
    shot = _add(client, scene)

    response = _save(client, scene, shot, layers=[layer])

    assert response.status_code == 400
    assert missing in response.json()["detail"]
    assert client.get(f"{scene['shots']}/{shot['id']}").json()["version"] == 0


def test_a_save_cannot_move_a_shot_or_change_its_id(client, scene):
    """
    Verifies that sending an order, scene or ID with a save changes none of them -- they come from the path and the stored shot.
    """
    shot = _add(client, scene)

    saved = _save(client, scene, shot, order=7, scene_id="elsewhere", id="other").json()

    assert (saved["id"], saved["scene_id"], saved["order"]) == (shot["id"], scene["id"], 0)


def test_every_shot_says_which_layers_are_out_of_date_and_what_changed(client, boards, scene):
    """
    Verifies out_of_date on the shot routes: a new shot's background is listed (never drawn), it's gone once drawn, and an edit to its location brings it back naming what changed -- on reading, listing and saving.
    """
    shot = _add(client, scene)
    background_id = shot["layers"][0]["id"]
    assert shot["out_of_date"] == {background_id: []}

    # Drawn, as generation would: an image, and the params it was drawn from
    stored = boards.get_shot(scene["pid"], scene["id"], shot["id"])
    stored_scene = boards.get_scene(scene["pid"], scene["id"])
    layer = stored.layers[0]
    entry = Registry.load(boards, scene["pid"]).entry_for(layer, stored_scene)
    drawn = layer.model_copy(update={"image": f"projects/{scene['pid']}/generated/plate.png", "last_generated_params": layer.current_params(stored.generation_context(stored_scene), entry)})
    boards.save_shot(scene["pid"], stored.model_copy(update={"layers": [drawn]}))
    assert client.get(f"{scene['shots']}/{shot['id']}").json()["out_of_date"] == {}

    assert client.patch(f"/projects/{scene['pid']}/locations/office", json={"description": "A cramped harbour office"}).status_code == 200
    assert client.get(scene["shots"]).json()[0]["out_of_date"] == {background_id: ["location_description"]}
    current = client.get(f"{scene['shots']}/{shot['id']}").json()
    assert _save(client, scene, current, shot_size="wide").json()["out_of_date"] == {background_id: ["shot_size", "location_description"]}


def test_image_urls_cover_every_layer_image_in_this_project_only(client, boards, scene):
    """
    Verifies that every layer image in the project gets a download URL (groups' children included), and an image key pointing elsewhere is never signed.
    """
    shot = _add(client, scene)
    own = f"projects/{scene['pid']}/uploads/a.png"
    nested = f"projects/{scene['pid']}/poses/mara.png"
    layers = [
        {"type": "image", "image": own},
        {"type": "group", "children": [{"type": "character", "character_id": "mara", "image": nested}]},
        {"type": "image", "image": "projects/someone-else/uploads/b.png"},
    ]

    urls = _save(client, scene, shot, layers=layers).json()["image_urls"]

    assert set(urls) == {own, nested}


def test_shots_are_reordered_and_each_moved_shot_gets_a_new_version(client, scene):
    """
    Verifies that PUT /order renumbers the shots in the order given, and that only the shots that moved are saved (their versions go up).
    """
    one, two, three = (_add(client, scene) for _ in range(3))

    reordered = client.put(f"{scene['shots']}/order", json={"shot_ids": [two["id"], one["id"], three["id"]]})

    assert reordered.status_code == 200
    assert [(s["id"], s["order"], s["version"]) for s in reordered.json()] == [(two["id"], 0, 1), (one["id"], 1, 1), (three["id"], 2, 0)]
    assert client.get(scene["shots"]).json() == reordered.json()


@pytest.mark.parametrize("ids", [
    lambda one, two: [one],                  # Missing a shot
    lambda one, two: [one, two, "extra"],    # A shot that isn't in the scene
    lambda one, two: [one, one],             # A repeat, standing in for the missing one
])
def test_a_reorder_must_list_every_shot_exactly_once(client, scene, ids):
    """
    Verifies that a missing, extra or repeated shot ID is a 400 that leaves the order alone.

    Arguments:
        ids: Callable - Builds the invalid list from the two shots' IDs.
    """
    one, two = _add(client, scene), _add(client, scene)

    response = client.put(f"{scene['shots']}/order", json={"shot_ids": ids(one["id"], two["id"])})

    assert response.status_code == 400
    assert [s["id"] for s in client.get(scene["shots"]).json()] == [one["id"], two["id"]]


def test_a_reorder_cannot_pull_in_another_scenes_shot(client, scene):
    """
    Verifies that a shot from another scene of the same project doesn't count as one of this scene's.
    """
    other_scene = client.post(f"/projects/{scene['pid']}/scenes", json={"location_id": "office"}).json()["id"]
    other = client.post(f"/projects/{scene['pid']}/scenes/{other_scene}/shots", json={}).json()
    mine = _add(client, scene)

    response = client.put(f"{scene['shots']}/order", json={"shot_ids": [other["id"], mine["id"]]})

    assert response.status_code == 400


def test_a_deleted_shot_is_gone_and_the_rest_stay(client, scene):
    """
    Verifies that DELETE answers 204 with no body, and removes only that shot.
    """
    doomed, kept = _add(client, scene), _add(client, scene)

    deleted = client.delete(f"{scene['shots']}/{doomed['id']}")

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert client.get(f"{scene['shots']}/{doomed['id']}").status_code == 404
    assert [s["id"] for s in client.get(scene["shots"]).json()] == [kept["id"]]


@pytest.mark.parametrize("method", ["get", "put", "delete"])
def test_an_unknown_shot_is_a_404(client, scene, method):
    """
    Verifies that every route naming a shot answers 404, with a message, when it doesn't exist.

    Arguments:
        method: str - HTTP method.
    """
    body = {"layers": [], "version": 0} if method == "put" else None

    response = client.request(method, f"{scene['shots']}/does-not-exist", json=body)

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_a_shot_is_only_found_through_its_own_scene(client, scene):
    """
    Verifies that a shot can't be read through another scene's path, even in the same project.
    """
    shot = _add(client, scene)
    other_scene = client.post(f"/projects/{scene['pid']}/scenes", json={"location_id": "office"}).json()["id"]

    assert client.get(f"/projects/{scene['pid']}/scenes/{other_scene}/shots/{shot['id']}").status_code == 404


@pytest.mark.parametrize("method, path, body", [("get", "", None), ("post", "", {}), ("put", "/order", {"shot_ids": []})])
def test_shots_in_an_unknown_scene_or_project_are_a_404(client, scene, method, path, body):
    """
    Verifies that the shot routes answer 404 for a scene, or a project, that doesn't exist.

    Arguments:
        method: str - HTTP method.
        path: str - Path after /shots.
        body: dict - Request body, if the route takes one.
    """
    unknown_scene = client.request(method, f"/projects/{scene['pid']}/scenes/does-not-exist/shots{path}", json=body)
    unknown_project = client.request(method, f"/projects/does-not-exist/scenes/{scene['id']}/shots{path}", json=body)

    assert (unknown_scene.status_code, unknown_project.status_code) == (404, 404)
    assert "does-not-exist" in unknown_scene.json()["detail"]
