"""
Unit tests for sketches: saving an entry's sketch for one slot, using its flattened image as that slot's reference or plate, and going back to the generated one.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py).
"""
import pytest

from taleboard.schema.storyboard import MAX_STROKE_POINTS, SKETCH_FRAMES, Character, Location

STROKE = {"points": [0, 0, 10, 10, 20, 5], "colour": "#222222", "width": 3}


@pytest.fixture
def pid(client):
    return client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]


@pytest.fixture
def entries(client, pid):
    """
    Mara (a character) and an office (a location), created through the API.
    """
    client.post(f"/projects/{pid}/characters", json={"name": "Mara"})
    client.post(f"/projects/{pid}/locations", json={"name": "Office"})


def _sketch_url(pid: str, registry: str = "characters", entry: str = "mara", slot: str = "left") -> str:
    return f"/projects/{pid}/{registry}/{entry}/sketches/{slot}"


def _freehand(*strokes: dict, layer_id: str = "pen") -> dict:
    return {"type": "freehand", "id": layer_id, "strokes": list(strokes)}


def test_a_new_sketch_is_saved_at_version_0_and_read_back_on_its_frame(client, pid, entries):
    """
    Verifies that a first save (version 0) creates the sketch on the frame for its registry, with its layers -- and that reading it gives it back.
    """
    saved = client.put(_sketch_url(pid), json={"layers": [_freehand(STROKE)], "version": 0})

    assert saved.status_code == 200
    body = saved.json()
    assert (body["registry"], body["entry_id"], body["slot"], body["version"]) == ("characters", "mara", "left", 1)
    assert (body["width"], body["height"]) == SKETCH_FRAMES["characters"]
    assert client.get(_sketch_url(pid)).json()["layers"][0]["strokes"][0]["points"] == STROKE["points"]


def test_a_location_sketch_is_kept_by_facing_on_a_square_frame(client, pid, entries):
    """
    Verifies that a location's sketches are by facing, on a square frame -- and that an orientation isn't a location slot.
    """
    body = client.put(_sketch_url(pid, "locations", "office", "south"), json={"layers": [], "version": 0}).json()

    assert (body["slot"], body["width"], body["height"]) == ("south", 1024, 1024)
    assert client.put(_sketch_url(pid, "locations", "office", "left"), json={"layers": [], "version": 0}).status_code == 422


def test_a_slot_with_no_sketch_or_an_unknown_entry_is_a_404(client, pid, entries):
    """
    Verifies the 404s: a slot that hasn't been sketched, and an entry that doesn't exist.
    """
    assert client.get(_sketch_url(pid, slot="right")).status_code == 404
    assert client.put(_sketch_url(pid, entry="ghost"), json={"layers": [], "version": 0}).status_code == 404


def test_saving_from_an_out_of_date_copy_is_a_409_with_the_current_version(client, pid, entries):
    """
    Verifies that sketches are version-checked like shots: a second "new" save, or one from an old version, is refused with the current version.
    """
    client.put(_sketch_url(pid), json={"layers": [], "version": 0})
    client.put(_sketch_url(pid), json={"layers": [_freehand(STROKE)], "version": 1})

    for stale in (0, 1):
        response = client.put(_sketch_url(pid), json={"layers": [], "version": stale})
        assert response.status_code == 409 and response.json()["current_version"] == 2


@pytest.mark.parametrize("layer", [
    {"type": "character", "character_id": "mara"},
    {"type": "background"},
    {"type": "group", "children": [{"type": "prop", "prop_id": "lamp"}]},
])
def test_a_sketch_never_holds_generated_layers(client, pid, entries, layer):
    """
    Verifies that a background, character or prop layer -- even inside a group -- is a 422 in a sketch.

    Arguments:
        layer: dict - The layer sent.
    """
    assert client.put(_sketch_url(pid), json={"layers": [layer], "version": 0}).status_code == 422


def test_a_drawing_too_big_to_store_is_a_422(client, pid, entries):
    """
    Verifies the stroke budget: more than MAX_STROKE_POINTS points across a sketch's freehand layers is refused before anything is written.
    """
    half = MAX_STROKE_POINTS // 2 + 1
    big = {"points": [0.0, 1.0] * half}

    response = client.put(_sketch_url(pid), json={"layers": [_freehand(big, layer_id="a"), _freehand(big, layer_id="b")], "version": 0})

    assert response.status_code == 422 and "at most" in str(response.json())


def test_using_a_sketch_makes_it_the_slots_reference(client, pid, entries):
    """
    Verifies that using an upload makes it the slot's sketched reference (with its background choice), and it's signed like any image.
    """
    image = f"projects/{pid}/uploads/mara-left.png"

    mara = client.put(f"{_sketch_url(pid)}/use", json={"image": image, "remove_background": False}).json()

    assert mara["references"]["left"] == {"image": image, "source": "sketch", "remove_background": False}
    assert image in mara["image_urls"]


def test_a_location_sketch_becomes_its_plate(client, pid, entries):
    """
    Verifies that using a location's sketch sets that facing's plate.
    """
    image = f"projects/{pid}/uploads/office-south.png"

    office = client.put(f"{_sketch_url(pid, 'locations', 'office', 'south')}/use", json={"image": image}).json()

    assert office["plates"]["south"]["source"] == "sketch" and office["plates"]["south"]["image"] == image


@pytest.mark.parametrize("image", ["projects/someone-else/uploads/x.png", "elsewhere/x.png"])
def test_only_this_projects_uploads_can_be_used(client, pid, entries, image):
    """
    Verifies that an image outside this project's uploads folder can't be made a sketch.

    Arguments:
        image: str - The key sent.
    """
    assert client.put(f"{_sketch_url(pid)}/use", json={"image": image}).status_code == 400


def test_going_back_to_generated_clears_the_slot_and_keeps_the_sketch(client, pid, entries, boards):
    """
    Verifies that stopping using a sketch empties its slot (drawn again when next needed) while the sketch itself stays -- and that doing so for a generated slot changes nothing.
    """
    client.put(_sketch_url(pid), json={"layers": [_freehand(STROKE)], "version": 0})
    client.put(f"{_sketch_url(pid)}/use", json={"image": f"projects/{pid}/uploads/mara-left.png"})

    mara = client.delete(f"{_sketch_url(pid)}/use").json()

    assert "left" not in mara["references"]
    assert "left" not in boards.get_entry(pid, Character, "mara").references
    assert client.get(_sketch_url(pid)).status_code == 200
    assert client.delete(f"{_sketch_url(pid, slot='right')}/use").status_code == 200


def test_deleting_an_entry_deletes_its_sketches(client, pid, entries, boards):
    """
    Verifies that an entry's sketches go with it -- and another entry's don't.
    """
    client.put(_sketch_url(pid), json={"layers": [], "version": 0})
    client.put(_sketch_url(pid, slot="right"), json={"layers": [], "version": 0})
    client.put(_sketch_url(pid, "locations", "office", "north"), json={"layers": [], "version": 0})

    client.delete(f"/projects/{pid}/characters/mara")

    for slot in ("left", "right"):
        with pytest.raises(KeyError):
            boards.get_sketch(pid, Character, "mara", slot)
    assert boards.get_sketch(pid, Location, "office", "north").version == 1


def test_a_sketchs_uploaded_images_are_signed(client, pid, entries):
    """
    Verifies that an image layer in a sketch gets a download URL, like a shot's.
    """
    image = f"projects/{pid}/uploads/photo.png"

    body = client.put(_sketch_url(pid), json={"layers": [{"type": "image", "image": image}], "version": 0}).json()

    assert image in body["image_urls"]
