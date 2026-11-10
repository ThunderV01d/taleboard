"""
Unit tests for the generation routes: previewing a Generate request, asking for it, and reading its job.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), with the generation queue swapped for a fake that records what's sent, so no AWS calls are made.
"""
import pytest

from taleboard.api.app import app
from taleboard.api.deps import get_generation_queue
from taleboard.schema.enums import Facing, ShotSize
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Scene, Shot


class FakeQueue:
    """
    Records each job queued, instead of sending it.
    """
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def enqueue(self, project_id: str, job_id: str) -> None:
        self.sent.append((project_id, job_id))


@pytest.fixture
def queue(client):
    """
    A fake generation queue, used by the API for the test.

    Arguments:
        client: TestClient - Client for the API (so the overrides are cleared after it).

    Returns:
        FakeQueue - The fake.
    """
    fake = FakeQueue()
    app.dependency_overrides[get_generation_queue] = lambda: fake
    return fake


@pytest.fixture
def story(client, boards):
    """
    A project with an office, Mara, and one scene of two shots: the first with a background, Mara and a caption; the second with its background already drawn.

    Returns:
        dict - The project's ID, its scene, and its two shots.
    """
    pid = client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]
    boards.create_entry(pid, Location, "Office", views={Facing.NORTH: "a window"})
    boards.create_entry(pid, Character, "Mara")
    scene = Scene(location_id="office")
    boards.create_scene(pid, scene)
    first = Shot(scene_id=scene.id, order=0, shot_size=ShotSize.MEDIUM, layers=[
        BackgroundLayer(id="bg1"), CharacterLayer(id="mara", character_id="mara", action="waving"), TextLayer(id="caption"),
    ])
    second = Shot(scene_id=scene.id, order=1, shot_size=ShotSize.WIDE)
    background = BackgroundLayer(id="bg2")
    office = boards.get_entry(pid, Location, "office")
    second.layers = [background.model_copy(update={"image": "x.png", "last_generated_params": background.current_params(second.generation_context(scene), office)})]
    boards.create_shot(pid, first)
    boards.create_shot(pid, second)
    return {"pid": pid, "scene": scene.id, "first": first.id, "second": second.id}


def test_a_preview_counts_the_layers_and_images_without_making_a_job(client, boards, queue, story):
    """
    Verifies that previewing the whole project counts what needs drawing -- and queues nothing.
    """
    plan = client.post(f"/projects/{story['pid']}/generate/preview", json={}).json()

    # bg1 and Mara (bg2 is up to date): north plate, medium framing, Mara's front reference, her pose
    assert plan == {"layers": 2, "images": 4}
    assert queue.sent == [] and boards.list_jobs(story["pid"]) == []


def test_generating_saves_the_jobs_tasks_in_order_then_queues_it(client, boards, queue, story):
    """
    Verifies that a Generate request makes a job of the layers needing drawing, in order, saved before it's queued.
    """
    response = client.post(f"/projects/{story['pid']}/generate", json={"scene_id": story["scene"]})
    job = response.json()

    assert response.status_code == 202
    assert [(t["shot_id"], t["layer_id"], t["status"]) for t in job["tasks"]] == [
        (story["first"], "bg1", "pending"), (story["first"], "mara", "pending"),
    ]
    assert job["status"] == "queued"
    assert queue.sent == [(story["pid"], job["id"])]
    assert boards.get_job(story["pid"], job["id"]).tasks[1].layer_id == "mara"


def test_one_layer_is_drawn_even_if_up_to_date(client, queue, story):
    """
    Verifies that naming a layer always draws it -- that's how one is redrawn.
    """
    body = {"scene_id": story["scene"], "shot_id": story["second"], "layer_id": "bg2"}

    assert client.post(f"/projects/{story['pid']}/generate/preview", json=body).json()["layers"] == 1
    assert [t["layer_id"] for t in client.post(f"/projects/{story['pid']}/generate", json=body).json()["tasks"]] == ["bg2"]


def test_nothing_to_draw_is_a_400_and_no_job(client, boards, queue, story):
    """
    Verifies that asking for a shot that's already up to date makes no job.
    """
    response = client.post(f"/projects/{story['pid']}/generate", json={"scene_id": story["scene"], "shot_id": story["second"]})

    assert response.status_code == 400
    assert queue.sent == [] and boards.list_jobs(story["pid"]) == []


@pytest.mark.parametrize("body", [{"shot_id": "x"}, {"scene_id": "x", "layer_id": "y"}])
def test_a_narrower_target_needs_the_wider_one_around_it(client, queue, story, body):
    """
    Verifies that a shot needs its scene, and a layer its shot.

    Arguments:
        body: dict - A request missing a wider target.
    """
    assert client.post(f"/projects/{story['pid']}/generate", json=body).status_code == 422


def test_unknown_targets_are_404s_and_a_text_layer_is_a_400(client, queue, story):
    """
    Verifies that a missing scene, shot or layer is a 404, and a layer that isn't generated is a 400.
    """
    pid, scene, first = story["pid"], story["scene"], story["first"]

    assert client.post(f"/projects/{pid}/generate", json={"scene_id": "nowhere"}).status_code == 404
    assert client.post(f"/projects/{pid}/generate", json={"scene_id": scene, "shot_id": "nowhere"}).status_code == 404
    assert client.post(f"/projects/{pid}/generate", json={"scene_id": scene, "shot_id": first, "layer_id": "nowhere"}).status_code == 404
    assert client.post(f"/projects/{pid}/generate", json={"scene_id": scene, "shot_id": first, "layer_id": "caption"}).status_code == 400
    assert queue.sent == []


def test_jobs_are_listed_newest_first_and_read_one_by_one(client, queue, story):
    """
    Verifies the job routes: the list (newest first), one job, and a 404 for one that doesn't exist.
    """
    pid = story["pid"]
    first = client.post(f"/projects/{pid}/generate", json={}).json()
    second = client.post(f"/projects/{pid}/generate", json={"scene_id": story["scene"], "shot_id": story["second"], "layer_id": "bg2"}).json()

    assert [job["id"] for job in client.get(f"/projects/{pid}/jobs").json()] == [second["id"], first["id"]]
    assert client.get(f"/projects/{pid}/jobs/{first['id']}").json()["tasks"] == first["tasks"]
    assert client.get(f"/projects/{pid}/jobs/missing").status_code == 404


def test_another_users_project_is_a_404_for_every_generation_route(client, boards, queue):
    """
    Verifies that generation routes check ownership like every other project route.
    """
    theirs = boards.create_project("Theirs", "someone-else").project_id

    assert client.post(f"/projects/{theirs}/generate/preview", json={}).status_code == 404
    assert client.post(f"/projects/{theirs}/generate", json={}).status_code == 404
    assert client.get(f"/projects/{theirs}/jobs").status_code == 404
    assert queue.sent == []
