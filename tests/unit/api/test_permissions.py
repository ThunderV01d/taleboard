"""
Unit tests for who may do what with a project: its owner, a user it's shared with to view, the shared guest user, and
everyone else.

Every route under /projects/{project_id} is checked by name, straight from the app's route table -- so a route added
later is covered without touching these tests: a viewer (and the guest) can use every GET route, and gets a 403 from
every other one (each write, upload and generation route) with nothing changed. Someone the project isn't shared with
gets a 404 from every route (see test_app.py).

Run with: pytest tests/unit/api/test_permissions.py
"""
import base64
import json

import pytest

from taleboard.api.app import app
from taleboard.api.deps import get_claims
from taleboard.auth import guest_session
from taleboard.schema.sharing import ShareRole
from taleboard.storage.storyboard_store import StoryboardStore

OWNER = "test-user"  # Who the client fixture signs in as (conftest.TEST_USER_ID)
VIEWER = "viewer-user"
GUEST = "guest-user"
STRANGER = "stranger"

PROJECT_ROUTES = sorted(
    (method, route.path)
    for route in app.routes if "{project_id}" in getattr(route, "path", "")
    for method in route.methods
)
READ_ROUTES = [(method, path) for method, path in PROJECT_ROUTES if method == "GET"]
WRITE_ROUTES = [(method, path) for method, path in PROJECT_ROUTES if method != "GET"]


def _as(user_id: str, guest: bool = False) -> None:
    """
    Switches the test client to another user -- the guest carries the guests group, in the string form API Gateway passes a list claim in.

    Arguments:
        user_id: str - The user to act as.
        guest: bool - Whether they're the guest. Defaults to False.
    """
    claims = {"sub": user_id, **({"cognito:groups": "[guests]"} if guest else {})}
    app.dependency_overrides[get_claims] = lambda: claims


@pytest.fixture
def shared(client, boards):
    """
    The owner's project -- a location, a character, a scene and a shot (with an image) -- shared to view with VIEWER and GUEST.

    Returns:
        dict - The project's ID ("pid"), and its scene's and shot's ("scene", "shot").
    """
    pid = client.post("/projects", json={"name": "Lighthouse"}).json()["project_id"]
    client.post(f"/projects/{pid}/locations", json={"name": "Office"})
    client.post(f"/projects/{pid}/characters", json={"name": "Mara"})
    scene = client.post(f"/projects/{pid}/scenes", json={"location_id": "office"}).json()["id"]
    shot = client.post(f"/projects/{pid}/scenes/{scene}/shots", json={}).json()
    layers = shot["layers"]
    layers[0]["image"] = f"projects/{pid}/generated/plate/abc.png"
    boards.put_image(layers[0]["image"], b"png")
    saved = client.put(f"/projects/{pid}/scenes/{scene}/shots/{shot['id']}", json={**{k: shot[k] for k in ("description", "duration_s", "shot_size", "angle", "details", "version")}, "layers": layers})
    assert saved.status_code == 200, saved.text
    for user in (VIEWER, GUEST):
        boards.share_project(pid, user, ShareRole.VIEWER, granted_by=OWNER)
    return {"pid": pid, "scene": scene, "shot": shot["id"]}


def claims_of(token: str) -> dict:
    """
    A JWT's claims (its payload), unverified -- API Gateway's authorizer does the verifying.
    """
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def _url(path: str, shared: dict) -> str:
    return path.format(project_id=shared["pid"], scene_id=shared["scene"], shot_id=shared["shot"], entry_id="mara", job_id="any-job", slot="towards_camera", grantee_id=VIEWER)


def _snapshot(boards: StoryboardStore, pid: str) -> tuple:
    """
    Everything a write could change: the project, its registries, scenes, shots (with versions), jobs, shares, and the images in its folder.
    """
    s3 = boards._s3.list_objects_v2(Bucket=boards._bucket, Prefix=f"projects/{pid}/").get("Contents", [])
    return (
        boards.get_project(pid),
        [item for item in boards._query(pid) if not item["SK"].startswith("SHARE#")],
        sorted(share.grantee_id for share in boards.list_shares(pid)),
        sorted(obj["Key"] for obj in s3),
    )


@pytest.mark.parametrize("guest", [False, True], ids=["viewer", "guest"])
@pytest.mark.parametrize("method, path", READ_ROUTES)
def test_a_viewer_can_use_every_read_route(client, shared, method, path, guest):
    """
    Verifies that a viewer (and the guest) gets every GET route under a shared project -- never a 403, nor the project's 404. (The share list is the owner's alone.)

    Arguments:
        method: str - HTTP method (GET).
        path: str - The route's path template.
        guest: bool - Whether it's the guest asking.
    """
    _as(GUEST if guest else VIEWER, guest)

    response = client.request(method, _url(path, shared))

    if path.endswith("/shares"):
        assert response.status_code == 403
    else:
        assert response.status_code != 403, response.text
        # A missing sub-resource (the made-up job, an unsketched slot) may still be a 404 -- but never the project's
        assert response.status_code < 400 or response.json()["detail"] != f"No project with ID {shared['pid']!r}"


@pytest.mark.parametrize("guest", [False, True], ids=["viewer", "guest"])
@pytest.mark.parametrize("method, path", WRITE_ROUTES)
def test_a_viewer_is_refused_every_write_upload_and_generation_route(client, boards, shared, method, path, guest):
    """
    Verifies that a viewer (and the guest) gets a 403 from every route that isn't a GET, by name -- and that nothing in the project, its images or the generation queue changed.

    Arguments:
        method: str - HTTP method.
        path: str - The route's path template.
        guest: bool - Whether it's the guest asking.
    """
    before = _snapshot(boards, shared["pid"])
    _as(GUEST if guest else VIEWER, guest)

    response = client.request(method, _url(path, shared), json={})

    assert response.status_code == 403, response.text
    assert _snapshot(boards, shared["pid"]) == before


def test_the_owner_can_read_and_change_their_own_project(client, shared):
    """
    Verifies that the owner still reads and writes as before.
    """
    pid = shared["pid"]

    assert client.get(f"/projects/{pid}").json()["access"] == "owner"
    assert client.patch(f"/projects/{pid}", json={"name": "Renamed"}).status_code == 200
    assert client.post(f"/projects/{pid}/uploads", json={"content_type": "image/png"}).status_code == 200


def test_the_project_is_a_404_to_anyone_it_is_not_shared_with(client, shared):
    """
    Verifies that sharing it with some users doesn't open it to anyone else.
    """
    _as(STRANGER)

    assert client.get(f"/projects/{shared['pid']}").status_code == 404
    assert client.get("/projects").json() == []


def test_the_project_list_has_owned_and_shared_projects_each_labelled(client, boards, shared):
    """
    Verifies GET /projects: the owner sees theirs as "owner"; a viewer sees what's shared with them as "viewer" (alongside their own); an unshared project is never listed.
    """
    unshared = client.post("/projects", json={"name": "Private"}).json()["project_id"]
    assert {p["project_id"]: p["access"] for p in client.get("/projects").json()} == {unshared: "owner", shared["pid"]: "owner"}

    _as(VIEWER)
    own = client.post("/projects", json={"name": "Viewer's own"}).json()["project_id"]
    assert {p["project_id"]: p["access"] for p in client.get("/projects").json()} == {own: "owner", shared["pid"]: "viewer"}
    assert client.get(f"/projects/{shared['pid']}").json()["access"] == "viewer"


def test_a_viewer_gets_working_image_urls(client, shared):
    """
    Verifies that a viewer is given the same presigned URLs as the owner for a shared project's images.
    """
    path = f"/projects/{shared['pid']}/scenes/{shared['scene']}/shots/{shared['shot']}"
    owners = client.get(path).json()["image_urls"]
    _as(VIEWER)
    viewers = client.get(path).json()["image_urls"]

    assert list(viewers) == list(owners) == [f"projects/{shared['pid']}/generated/plate/abc.png"]
    assert all(url.startswith("https://") for url in viewers.values())


def test_the_guest_can_create_nothing_of_its_own(client, boards):
    """
    Verifies that the guest is refused creating a project -- it would own it, and could then generate in it -- so it never owns anything.
    """
    _as(GUEST, guest=True)

    response = client.post("/projects", json={"name": "Free images"})

    assert response.status_code == 403
    assert boards.list_projects(GUEST) == []


def test_the_guest_cannot_generate_even_if_it_were_granted_editor(client, boards, shared):
    """
    Verifies the guest's second lock: shared as an editor (which the share route refuses -- so straight in the store), it still can't generate, import, upload or save.
    """
    boards.share_project(shared["pid"], GUEST, ShareRole.EDITOR, granted_by=OWNER)
    _as(GUEST, guest=True)
    pid = shared["pid"]

    for method, url, body in [
        ("post", f"/projects/{pid}/generate", {}),
        ("post", f"/projects/{pid}/generate/preview", {}),
        ("post", f"/projects/{pid}/import", {"story": "Mara climbs the stairs."}),
        ("post", f"/projects/{pid}/uploads", {"content_type": "image/png"}),
        ("patch", f"/projects/{pid}", {"name": "Mine now"}),
    ]:
        assert client.request(method, url, json=body).status_code == 403, url
    assert boards.list_jobs(pid) == []


def test_the_guest_is_spotted_by_its_app_client_too(client, shared, monkeypatch):
    """
    Verifies that a token from the guest app client is the guest even without the group claim.
    """
    monkeypatch.setenv("TALEBOARD_GUEST_CLIENT_ID", "guest-client")
    app.dependency_overrides[get_claims] = lambda: {"sub": VIEWER, "client_id": "guest-client"}

    assert client.get(f"/projects/{shared['pid']}").status_code == 200
    assert client.post("/projects", json={"name": "Nope"}).status_code == 403


def test_only_the_owner_can_share_and_only_to_view(client, boards, shared):
    """
    Verifies the share routes: the owner shares to view, lists and stops sharing; editor (not grantable yet) and sharing with yourself are refused; a viewer can't touch any of it.
    """
    pid = shared["pid"]
    assert client.put(f"/projects/{pid}/shares/new-user", json={"role": "viewer"}).json()["role"] == "viewer"
    assert sorted(s["grantee_id"] for s in client.get(f"/projects/{pid}/shares").json()) == [GUEST, "new-user", VIEWER]
    assert client.put(f"/projects/{pid}/shares/other", json={"role": "editor"}).status_code == 400
    assert client.put(f"/projects/{pid}/shares/{OWNER}", json={"role": "viewer"}).status_code == 400

    assert client.delete(f"/projects/{pid}/shares/{VIEWER}").status_code == 204
    _as(VIEWER)
    assert client.get(f"/projects/{pid}").status_code == 404  # No longer shared with them
    assert client.put(f"/projects/{pid}/shares/{VIEWER}", json={"role": "viewer"}).status_code == 404


def test_deleting_a_project_deletes_its_shares(client, boards, shared):
    """
    Verifies that a deleted project disappears from its viewers' lists, its shares gone with it.
    """
    assert client.delete(f"/projects/{shared['pid']}").status_code == 204

    assert boards.list_shared_with(VIEWER) == []
    _as(VIEWER)
    assert client.get("/projects").json() == []


def test_the_guest_token_reads_a_shared_project_but_not_an_unshared_one(guest_pool, client, boards):
    """
    Verifies end to end (but for API Gateway's signature check): the claims of a token from POST /auth/guest reach a project shared with the guest, read-only, and nothing else.
    """
    shared = client.post("/projects", json={"name": "Seeded"}).json()["project_id"]
    unshared = client.post("/projects", json={"name": "Private"}).json()["project_id"]
    claims = claims_of(json.loads(guest_session.handler({}, None)["body"])["access_token"])
    boards.share_project(shared, claims["sub"], ShareRole.VIEWER, granted_by="test-user")
    app.dependency_overrides[get_claims] = lambda: claims

    assert client.get(f"/projects/{shared}").json()["access"] == "viewer"
    assert client.get(f"/projects/{unshared}").status_code == 404
    assert [p["project_id"] for p in client.get("/projects").json()] == [shared]
    assert client.patch(f"/projects/{shared}", json={"name": "Mine"}).status_code == 403
