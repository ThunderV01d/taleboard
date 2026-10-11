"""
Unit tests for the HTTP API.

Uses FastAPI's test client against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py), so no AWS calls are made and nothing is rendered.
"""
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from taleboard.api.app import app, get_queue, get_store
from taleboard.schema.enums import CameraAngle, ProjectStatus, ShotSize
from taleboard.schema.models import Character, Shot


@pytest.fixture
def client(store, queue):
    """
    A test client whose store and queue are the fakes.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.

    Returns:
        TestClient - Client for the API.
    """
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_queue] = lambda: queue
    yield TestClient(app)
    app.dependency_overrides.clear()


def _shot(index: int) -> Shot:
    """
    Builds a character-less shot.

    Arguments:
        index: int - Used in the description and setting, and as the paragraph index.

    Returns:
        Shot - A Shot object.
    """
    return Shot(description=f"shot {index}", setting=f"setting {index}", regions=[], paragraph_index=index,
                shot_size=ShotSize.MEDIUM, angle=CameraAngle.EYE_LEVEL, duration_s=2.0)


def _create(client) -> str:
    """
    Creates a project through the API.

    Arguments:
        client: TestClient - Client for the API.

    Returns:
        str - The new project's ID.
    """
    return client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]


def test_projects_can_be_created_read_and_listed(client):
    """
    Verifies the project endpoints: create returns 201, and the project can then be read and listed.

    Arguments:
        client: TestClient - Client for the API.
    """
    response = client.post("/projects", json={"name": "Lighthouse"})
    assert response.status_code == 201
    project = response.json()
    assert project["status"] == "created"

    assert client.get(f"/projects/{project['project_id']}").json()["name"] == "Lighthouse"
    assert [p["project_id"] for p in client.get("/projects").json()] == [project["project_id"]]


def test_an_unknown_project_is_a_404_everywhere(client):
    """
    Verifies that every project endpoint responds 404 for a project that doesn't exist.

    Arguments:
        client: TestClient - Client for the API.
    """
    for path in ("", "/status", "/shots", "/shots/0", "/characters"):
        assert client.get(f"/projects/nope{path}").status_code == 404
    assert client.post("/projects/nope/story", json={"story": "Alice waved."}).status_code == 404


def test_submitting_a_story_queues_a_job_and_returns_202(client, queue):
    """
    Verifies that a story is accepted immediately -- 202, with the job queued and the project pending.

    Arguments:
        client: TestClient - Client for the API.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _create(client)

    response = client.post(f"/projects/{pid}/story", json={"story": "Alice waved."})

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    message = queue._sqs.receive_message(QueueUrl=queue._queue_url)["Messages"][0]
    assert json.loads(message["Body"]) == {"project_id": pid, "job_id": job_id}
    assert client.get(f"/projects/{pid}/status").json()["status"] == "pending"


def test_a_second_story_is_a_409_and_a_blank_one_a_422(client):
    """
    Verifies that a project with a story turns away another, and that a blank story never gets stored.

    Arguments:
        client: TestClient - Client for the API.
    """
    pid = _create(client)
    assert client.post(f"/projects/{pid}/story", json={"story": "   \n\n "}).status_code == 422
    assert client.post(f"/projects/{pid}/story", json={"story": "Alice waved."}).status_code == 202
    assert client.post(f"/projects/{pid}/story", json={"story": "Bob waved."}).status_code == 409


def test_a_failed_enqueue_fails_the_project_so_it_can_be_resubmitted(client, queue, monkeypatch):
    """
    Verifies that if the job can't be queued, the client gets a 503 and the project is failed rather than stuck at pending.

    Arguments:
        client: TestClient - Client for the API.
        queue: JobQueue - Fake-backed queue.
        monkeypatch: pytest.MonkeyPatch - Used to make queuing fail.
    """
    pid = _create(client)
    monkeypatch.setattr(queue, "enqueue", lambda project_id, job_id: (_ for _ in ()).throw(RuntimeError("SQS is down")))

    assert client.post(f"/projects/{pid}/story", json={"story": "Alice waved."}).status_code == 503
    assert client.get(f"/projects/{pid}/status").json()["status"] == "failed"


def test_status_and_shots_show_progress_part_way_through_a_job(client, store):
    """
    Verifies progressive completion: part-way through a job, status counts rendered shots, and finished shots are readable with an image URL while the rest aren't rendered yet.

    Arguments:
        client: TestClient - Client for the API.
        store: ProjectStore - Fake-backed store, used to play the worker's part.
    """
    pid = _create(client)
    job_id = client.post(f"/projects/{pid}/story", json={"story": "Alice waved."}).json()["job_id"]
    store.claim_job(pid, job_id)
    store.save_breakdown(pid, {}, [_shot(0), _shot(1), _shot(2)])
    store.save_rendered_shot(pid, 0, _shot(0), b"png", needs_review=True)

    assert client.get(f"/projects/{pid}/status").json() == {
        "status": "in_progress", "total_shots": 3, "rendered_shots": 1, "shots_needing_review": 1, "error": None,
    }
    shots = client.get(f"/projects/{pid}/shots").json()
    assert [(s["shot_id"], s["rendered"]) for s in shots] == [("0000", True), ("0001", False), ("0002", False)]
    assert shots[0]["image_url"].startswith("https://") and shots[1]["image_url"] is None

    assert client.get(f"/projects/{pid}/shots/0").json()["needs_review"] is True
    assert client.get(f"/projects/{pid}/shots/0002").json()["shot_id"] == "0002"
    assert client.get(f"/projects/{pid}/shots/3").status_code == 404
    assert client.get(f"/projects/{pid}/shots/abc").status_code == 404


def test_characters_are_listed_with_their_reference_image_url(client, store):
    """
    Verifies that the cast is listed, with a download URL only for characters whose reference image exists.

    Arguments:
        client: TestClient - Client for the API.
        store: ProjectStore - Fake-backed store, used to play the worker's part.
    """
    pid = _create(client)
    store.save_characters(pid, {"alice": Character(name="Alice", description="A woman.", aliases=["Al"]), "bob": Character(name="Bob", description="A man.")})
    store.put_reference(pid, "alice", b"png")

    characters = {c["character_id"]: c for c in client.get(f"/projects/{pid}/characters").json()}

    assert characters["alice"]["aliases"] == ["Al"]
    assert characters["alice"]["appearance_reference_url"].startswith("https://")
    assert characters["bob"]["appearance_reference"] is None and characters["bob"]["appearance_reference_url"] is None


def test_the_api_never_loads_the_rendering_pipeline():
    """
    Verifies that importing the API doesn't import taleboard.rendering, which would load the image models on every API cold start.

    Runs in a fresh interpreter, as other tests in this process have already imported rendering.
    """
    check = "import sys, taleboard.api.app; sys.exit('taleboard.rendering' in ' '.join(sys.modules))"
    assert subprocess.run([sys.executable, "-c", check]).returncode == 0