"""
Unit tests for the HTTP API.

Uses FastAPI's test client against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py, and tests/unit/api/conftest.py for the client), so no AWS calls are made.

Covers the sign-in check, and the project routes.
"""
import subprocess
import sys

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from taleboard.api.app import app
from taleboard.api.deps import get_boards, get_user_id

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


def test_a_project_is_created_read_and_listed(client, user_id):
    """
    Verifies that a created project comes back with its ID, name, owner (the signed-in user) and creation time, and can be read and listed.
    """
    created = client.post("/projects", json={"name": "Lighthouse"})

    assert created.status_code == 201
    project = created.json()
    assert set(project) == {"project_id", "name", "owner_id", "created_at"}
    assert project["owner_id"] == user_id
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


def _as(user_id: str) -> None:
    """
    Switches the test client to another signed-in user.

    Arguments:
        user_id: str - The user to act as.
    """
    app.dependency_overrides[get_user_id] = lambda: user_id


def test_each_user_only_lists_their_own_projects(client, user_id):
    """
    Verifies that the project list is per user.
    """
    mine = _create(client, "Mine")
    _as("someone-else")
    theirs = _create(client, "Theirs")

    assert [p["project_id"] for p in client.get("/projects").json()] == [theirs]
    _as(user_id)
    assert [p["project_id"] for p in client.get("/projects").json()] == [mine]


PROJECT_ROUTES = sorted(
    (method, route.path)
    for route in app.routes if "{project_id}" in getattr(route, "path", "")
    for method in route.methods
)


@pytest.mark.parametrize("method, path", PROJECT_ROUTES)
def test_no_route_lets_one_user_into_another_users_project(client, boards, method, path):
    """
    Verifies, for every route under /projects/{project_id} (including any added later), that another user gets the same 404 as for a project that doesn't exist -- and changes nothing.

    Arguments:
        method: str - HTTP method.
        path: str - The route's path template.
    """
    pid = _create(client)
    client.post(f"/projects/{pid}/locations", json={"name": "Office"})
    scene = client.post(f"/projects/{pid}/scenes", json={"location_id": "office"}).json()["id"]
    shot = client.post(f"/projects/{pid}/scenes/{scene}/shots", json={}).json()["id"]
    url = path.format(project_id=pid, scene_id=scene, shot_id=shot, entry_id="office", job_id="any-job")
    _as("intruder")

    response = client.request(method, url)

    assert response.status_code == 404
    assert response.json()["detail"] == f"No project with ID {pid!r}"
    assert boards.get_project(pid).name == "Lighthouse"
    assert [s.id for s in boards.list_scenes(pid)] == [scene]


def test_requests_without_a_signed_in_user_are_rejected_with_401(boards, user_id):
    """
    Verifies that the app fails closed: a request that reaches it without the authorizer's verified claims is refused, on reads and writes alike.
    """
    app.dependency_overrides[get_boards] = lambda: boards  # The store, but no stand-in user
    try:
        anonymous = TestClient(app)
        for response in (anonymous.get("/projects"), anonymous.post("/projects", json={"name": "Lighthouse"})):
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
        assert boards.list_projects(user_id) == []  # The refused create never happened
    finally:
        app.dependency_overrides.clear()


def _request(event: dict) -> Request:
    """
    Builds a request the way Mangum does, with the Lambda event in its scope.

    Arguments:
        event: dict - The API Gateway event.

    Returns:
        Request - The request.
    """
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "aws.event": event})


def test_the_user_id_is_the_sub_claim_the_authorizer_verified():
    """
    Verifies that get_user_id reads the token's sub from where API Gateway's JWT authorizer puts the verified claims.
    """
    event = {"version": "2.0", "requestContext": {"authorizer": {"jwt": {"claims": {"sub": "user-123", "client_id": "web"}, "scopes": None}}}}

    assert get_user_id(_request(event)) == "user-123"


@pytest.mark.parametrize("event", [
    {"version": "2.0", "requestContext": {}},                                  # No authorizer on the route
    {"version": "2.0", "requestContext": {"authorizer": {"jwt": {"claims": {}}}}},  # Claims without a sub
    {"version": "2.0", "requestContext": {"authorizer": None}},
])
def test_a_request_without_verified_claims_has_no_user(event):
    """
    Verifies that get_user_id refuses with a 401 whenever the verified sub is missing, instead of letting the request through.

    Arguments:
        event: dict - An API Gateway event without a verified sub.
    """
    with pytest.raises(HTTPException) as refused:
        get_user_id(_request(event))

    assert refused.value.status_code == 401


def test_a_request_that_bypassed_lambda_has_no_user():
    """
    Verifies that a request with no Lambda event at all (eg:- the app run directly) is refused, not treated as anyone.
    """
    with pytest.raises(HTTPException):
        get_user_id(Request({"type": "http", "method": "GET", "path": "/", "headers": []}))


def test_the_api_never_loads_the_image_models_or_the_story_breakdown():
    """
    Verifies that importing the API doesn't import background removal (which loads the image models) or the story breakdown -- either would slow every API cold start.

    Runs in a fresh interpreter, as other tests in this process have already imported them.
    """
    heavy = ["taleboard.generation.background_removal", "rembg", "taleboard.parsing.story_breakdown"]
    check = f"import sys, taleboard.api.app; sys.exit(any(name in sys.modules for name in {heavy!r}))"
    assert subprocess.run([sys.executable, "-c", check]).returncode == 0


@pytest.mark.parametrize("schema, fields", [
    ("Project", {"project_id", "name", "owner_id", "created_at"}),
    ("Scene", {"id", "name", "order", "location_id"}),
    ("ShotOut", {"id", "layers", "version", "image_urls"}),
    ("GroupLayer-Output", {"id", "transform", "children", "opacity", "visible"}),
    ("Usage", {"scenes"}),
])
def test_response_schemas_list_fields_with_defaults_as_required(schema, fields):
    """
    Verifies that response schemas mark fields with defaults (ids, transforms, lists) as required -- the API always
    sends them, so the frontend's generated types shouldn't make them optional.

    Arguments:
        schema: str - A response schema's name.
        fields: set[str] - Fields with defaults that it must list as required.
    """
    assert fields <= set(app.openapi()["components"]["schemas"][schema]["required"])


def test_request_schemas_still_let_defaults_be_left_out():
    """
    Verifies that the change is only to response schemas: a request may still leave out a layer's id or transform.
    """
    schemas = app.openapi()["components"]["schemas"]

    assert "id" not in schemas["TextLayer-Input"].get("required", [])
    assert "transform" not in schemas["TextLayer-Input"].get("required", [])
