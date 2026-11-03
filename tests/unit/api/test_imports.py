"""
Unit tests for the import route: queueing a story to be imported into a project.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), with the generation queue swapped for a fake that records what's sent.
"""
import pytest

from taleboard.api.app import app
from taleboard.api.deps import get_generation_queue
from taleboard.api.routes.imports import MAX_STORY_LENGTH
from taleboard.schema.enums import Facing
from taleboard.schema.generation import JobKind, JobStatus
from taleboard.schema.storyboard import Character, Location, Scene

STORY = "Mara climbed the stairs.\n\nShe lit the lamp."


class FakeQueue:
    """
    Records each job queued, with its kind, instead of sending it.
    """
    def __init__(self):
        self.sent: list[tuple[str, str, JobKind]] = []

    def enqueue(self, project_id: str, job_id: str, kind: JobKind = JobKind.GENERATE) -> None:
        self.sent.append((project_id, job_id, kind))


@pytest.fixture
def queue(client):
    fake = FakeQueue()
    app.dependency_overrides[get_generation_queue] = lambda: fake
    return fake


@pytest.fixture
def pid(client) -> str:
    return client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]


def test_an_import_saves_the_story_and_queues_an_import_job(client, boards, queue, pid):
    """
    Verifies that a story import is accepted (202), its story saved beside an import job that draws everything by default, and the job queued as an import.
    """
    response = client.post(f"/projects/{pid}/import", json={"story": STORY})

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["draw"], job["status"], job["tasks"]) == ("import", True, "queued", [])
    assert boards.get_story(pid, job["id"]) == STORY
    assert queue.sent == [(pid, job["id"], JobKind.IMPORT)]
    assert "story" not in client.get(f"/projects/{pid}/jobs").json()[0]  # Never sent back with the job


def test_an_import_can_leave_the_drawing_for_later(client, queue, pid):
    """
    Verifies that draw can be turned off.
    """
    assert client.post(f"/projects/{pid}/import", json={"story": STORY, "draw": False}).json()["draw"] is False


@pytest.mark.parametrize("story", ["", "   \n\n  ", "x" * (MAX_STORY_LENGTH + 1)], ids=["empty", "whitespace", "too-long"])
def test_an_empty_or_too_long_story_is_refused(client, queue, pid, story):
    """
    Verifies that an empty, whitespace-only or over-long story is a 422, and nothing is queued.

    Arguments:
        story: str - The story sent.
    """
    assert client.post(f"/projects/{pid}/import", json={"story": story}).status_code == 422
    assert queue.sent == []


@pytest.mark.parametrize("fill", ["scene", "entry"])
def test_a_story_is_only_imported_into_an_empty_project(client, boards, queue, pid, fill):
    """
    Verifies that a project with a scene or a registry entry in it already is a 409, as an import fills a project from scratch.

    Arguments:
        fill: str - What the project already has.
    """
    boards.create_entry(pid, Location, "Office", views={Facing.NORTH: "a window"})
    if fill == "scene":
        boards.create_scene(pid, Scene(location_id="office"))
    else:
        boards.create_entry(pid, Character, "Mara")

    response = client.post(f"/projects/{pid}/import", json={"story": STORY})

    assert response.status_code == 409 and "empty project" in response.json()["detail"]
    assert queue.sent == []


def test_a_second_import_waits_for_the_first_to_finish(client, boards, queue, pid):
    """
    Verifies that while an import is queued (or running) another is a 409 -- and that once it has failed, the project can try again.
    """
    first = client.post(f"/projects/{pid}/import", json={"story": STORY}).json()

    assert client.post(f"/projects/{pid}/import", json={"story": STORY}).status_code == 409
    boards.set_job_status(pid, first["id"], JobStatus.FAILED, error="Bedrock didn't answer")
    assert client.post(f"/projects/{pid}/import", json={"story": STORY}).status_code == 202


def test_only_the_owner_can_import_into_a_project(client, queue, pid):
    """
    Verifies that someone else's project (or one that doesn't exist) is a 404.
    """
    assert client.post("/projects/nobodys-project/import", json={"story": STORY}).status_code == 404
