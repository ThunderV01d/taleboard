"""
Unit tests for the HTTP API.

Uses FastAPI's test client against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py, and tests/unit/api/conftest.py for the client), so no AWS calls are made.

Covers the shared API key check, and the project routes.
"""
import subprocess
import sys

import boto3
import pytest
from fastapi.testclient import TestClient

from taleboard.api.app import app, get_api_key

def _create(client, name: str = "Lighthouse") -> str:
    """
    Creates a project through the API.

    Arguments:
        client: TestClient - Client for the API.
        name: str - Name of the project. Defaults to "Lighthouse".

    Returns:
        str - The new project's ID.
    """
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()["project_id"]


def test_a_project_is_created_read_and_listed(client):
    """
    Verifies that a created project comes back with its ID, name and creation time, and can be read and listed.
    """
    created = client.post("/projects", json={"name": "Lighthouse"})

    assert created.status_code == 201
    project = created.json()
    assert set(project) == {"project_id", "name", "created_at"}
    assert client.get(f"/projects/{project['project_id']}").json() == project
    assert project in client.get("/projects").json()


def test_projects_are_listed_newest_first(client):
    """
    Verifies that the project list is newest first.
    """
    for name in ("First", "Second", "Third"):
        _create(client, name)

    listed = client.get("/projects").json()

    assert [p["created_at"] for p in listed] == sorted((p["created_at"] for p in listed), reverse=True)


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "x" * 201}, {}, {"title": "Lighthouse"}])
def test_a_project_needs_a_name_of_1_to_200_characters(client, body):
    """
    Verifies that an empty, over-long or missing name is refused with a 422, before anything is created.

    Arguments:
        body: dict - An invalid request body.
    """
    assert client.post("/projects", json=body).status_code == 422
    assert client.get("/projects").json() == []


def test_a_project_can_be_renamed(client):
    """
    Verifies that PATCH renames a project, keeps its ID and creation time, and refuses an empty name.
    """
    pid = _create(client)
    before = client.get(f"/projects/{pid}").json()

    renamed = client.patch(f"/projects/{pid}", json={"name": "The Lighthouse"})

    assert renamed.status_code == 200
    assert renamed.json() == {**before, "name": "The Lighthouse"}
    assert client.patch(f"/projects/{pid}", json={"name": ""}).status_code == 422
    assert client.get(f"/projects/{pid}").json()["name"] == "The Lighthouse"


def test_a_deleted_project_is_gone(client, boards):
    """
    Verifies that DELETE answers 204 with no body, after which the project is gone from reads, the list and S3.
    """
    pid = _create(client)
    boards._s3.put_object(Bucket=boards._bucket, Key=f"projects/{pid}/uploads/a.png", Body=b"png")

    deleted = client.delete(f"/projects/{pid}")

    assert (deleted.status_code, deleted.content) == (204, b"")
    assert client.get(f"/projects/{pid}").status_code == 404
    assert client.get("/projects").json() == []
    assert "Contents" not in boards._s3.list_objects_v2(Bucket=boards._bucket, Prefix=f"projects/{pid}/")


@pytest.mark.parametrize("method, body", [("get", None), ("patch", {"name": "New"}), ("delete", None)])
def test_an_unknown_project_is_a_404(client, method, body):
    """
    Verifies that every route naming a project answers 404, with a message, when it doesn't exist.

    Arguments:
        method: str - HTTP method.
        body: dict - Request body, if the route takes one.
    """
    response = client.request(method, "/projects/does-not-exist", json=body)

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_requests_without_a_valid_api_key_are_rejected_with_401(client):
    """
    Verifies that a missing or wrong API key gets a 401, on reads and writes alike.
    """
    no_key = TestClient(app)  # Same overrides, but sends no key
    assert no_key.get("/projects").status_code == 401
    assert no_key.post("/projects", json={"name": "Lighthouse"}).status_code == 401

    wrong_key = client.get("/projects", headers={"X-API-Key": "wrong-key"})
    assert wrong_key.status_code == 401
    assert wrong_key.headers["www-authenticate"] == "APIKey"

    assert client.get("/projects").status_code == 200
    assert client.get("/projects").json() == []  # The unauthorised create never happened


def test_the_api_key_is_read_from_parameter_store(aws, monkeypatch):
    """
    Verifies that the expected API key comes from SSM Parameter Store.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes (provides fake credentials and an active moto mock).
        monkeypatch: pytest.MonkeyPatch - Used to point the API at the parameter.
    """
    boto3.client("ssm").put_parameter(Name="/taleboard/api-key", Value="secret-api-key", Type="SecureString")
    monkeypatch.setenv("TALEBOARD_API_KEY_PARAMETER", "/taleboard/api-key")
    get_api_key.cache_clear()
    try:
        assert get_api_key() == "secret-api-key"
    finally:
        get_api_key.cache_clear()  # Don't leak the cached key into other tests


def test_the_api_never_loads_the_rendering_pipeline():
    """
    Verifies that importing the API doesn't import taleboard.rendering, which would load the image models on every API cold start.

    Runs in a fresh interpreter, as other tests in this process have already imported rendering.
    """
    check = "import sys, taleboard.api.app; sys.exit('taleboard.rendering' in ' '.join(sys.modules))"
    assert subprocess.run([sys.executable, "-c", check]).returncode == 0
