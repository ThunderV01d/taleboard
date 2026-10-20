"""
Unit tests for the upload route.

Uses FastAPI's test client against moto's fakes (see tests/unit/api/conftest.py), so no AWS calls are made.

Covers the presigned upload form: where it uploads to, and the limits S3 is told to enforce (key, image type and size). S3 itself enforces them, so the tests read the signed policy rather than trying oversized uploads.
"""
import base64
import json

import pytest
import requests

from taleboard.api.routes.uploads import MAX_UPLOAD_BYTES


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


def _policy(form: dict) -> list:
    """
    Reads the conditions out of an upload form's signed policy.

    Arguments:
        form: dict - The route's response.

    Returns:
        list - The policy's conditions.
    """
    return json.loads(base64.b64decode(form["fields"]["policy"]))["conditions"]


@pytest.mark.parametrize("content_type, extension", [("image/png", "png"), ("image/jpeg", "jpg")])
def test_an_upload_goes_to_a_new_key_in_the_projects_uploads_folder(client, pid, content_type, extension):
    """
    Verifies that each upload gets its own key under projects/{pid}/uploads/, with the extension of its type.

    Arguments:
        content_type: str - Image type.
        extension: str - Expected file extension.
    """
    first = client.post(f"/projects/{pid}/uploads", json={"content_type": content_type})
    second = client.post(f"/projects/{pid}/uploads", json={"content_type": content_type})

    assert first.status_code == 200
    key = first.json()["key"]
    assert key.startswith(f"projects/{pid}/uploads/") and key.endswith(f".{extension}")
    assert second.json()["key"] != key
    assert first.json()["fields"]["key"] == key


def test_the_form_limits_the_key_type_and_size(client, pid):
    """
    Verifies that the signed policy pins the bucket, the exact key and content type, and a size between 1 byte and the maximum.
    """
    form = client.post(f"/projects/{pid}/uploads", json={"content_type": "image/png"}).json()

    conditions = _policy(form)

    assert {"key": form["key"]} in conditions
    assert {"Content-Type": "image/png"} in conditions
    assert ["content-length-range", 1, MAX_UPLOAD_BYTES] in conditions
    assert any("bucket" in condition for condition in conditions if isinstance(condition, dict))
    assert (form["fields"]["Content-Type"], form["max_bytes"]) == ("image/png", MAX_UPLOAD_BYTES)


@pytest.mark.parametrize("body", [{"content_type": "image/gif"}, {"content_type": "text/html"}, {"content_type": "image/svg+xml"}, {}])
def test_only_png_and_jpeg_can_be_uploaded(client, pid, body):
    """
    Verifies that any other type -- notably SVG and HTML, which a browser would run scripts in -- is a 422.

    Arguments:
        body: dict - A request for an unsupported type.
    """
    assert client.post(f"/projects/{pid}/uploads", json=body).status_code == 422


def test_an_upload_lands_at_its_key(client, boards, pid):
    """
    Verifies the whole round trip against the fake bucket: POSTing the form with a file stores it at the key the route returned, with its type.
    """
    form = client.post(f"/projects/{pid}/uploads", json={"content_type": "image/png"}).json()

    uploaded = requests.post(form["url"], data=form["fields"], files={"file": ("sketch.png", b"png bytes")})

    assert uploaded.status_code in (200, 204), uploaded.text
    stored = boards._s3.get_object(Bucket=boards._bucket, Key=form["key"])
    assert (stored["Body"].read(), stored["ContentType"]) == (b"png bytes", "image/png")


def test_uploads_to_an_unknown_project_are_a_404(client):
    """
    Verifies that no upload form is handed out for a project that doesn't exist.
    """
    assert client.post("/projects/does-not-exist/uploads", json={"content_type": "image/png"}).status_code == 404


def test_starting_an_upload_stores_nothing(client, boards, pid):
    """
    Verifies that handing out a form writes nothing to the bucket -- the file only exists once the browser uploads it.
    """
    client.post(f"/projects/{pid}/uploads", json={"content_type": "image/png"})

    assert "Contents" not in boards._s3.list_objects_v2(Bucket=boards._bucket, Prefix=f"projects/{pid}/")
