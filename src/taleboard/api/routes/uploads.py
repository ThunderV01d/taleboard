"""
Route for uploading images (sketches and image layers) straight from the browser to S3.

The API never handles the file itself: it hands out a presigned form that lets the browser POST one image to one new key in the project's uploads folder. S3 enforces the form's limits -- the key, the image type and the size -- so the bytes never pass through the API Lambda.

Attributes:
    UPLOAD_TYPES: dict[str,str] - The image types that can be uploaded, and the file extension each is stored with.
    MAX_UPLOAD_BYTES: int - Largest image S3 will accept (in bytes).
    UPLOAD_URL_EXPIRY_S: int - How long an upload form stays valid (in seconds).
"""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from taleboard.api.deps import get_boards, get_project
from taleboard.schema.storyboard import Project
from taleboard.storage.storyboard_store import StoryboardStore

UPLOAD_TYPES = {"image/png": "png", "image/jpeg": "jpg"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_URL_EXPIRY_S = 600

router = APIRouter(prefix="/projects/{project_id}/uploads", tags=["uploads"])


class UploadIn(BaseModel):
    """
    Request body for starting an upload.

    Attributes:
        content_type: str - The image's MIME type: image/png or image/jpeg.
    """
    content_type: Literal["image/png", "image/jpeg"]

class UploadOut(BaseModel):
    """
    Everything the browser needs to upload the image, and the key to use once it has.

    Attributes:
        key: str - S3 key the image will be stored at -- what an image layer's (or sketched reference's) image is set to.
        url: str - URL to POST the form to.
        fields: dict[str,str] - Form fields to send, before the file itself.
        max_bytes: int - Largest file S3 will accept, so the browser can refuse a bigger one without trying.
    """
    key: str
    url: str
    fields: dict[str, str]
    max_bytes: int


@router.post("", response_model=UploadOut)
def start_upload(body: UploadIn, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> UploadOut:
    """
    Hands out a form for uploading one image to a new key in the project's uploads folder.
    """
    key = f"projects/{project.project_id}/uploads/{uuid.uuid4().hex}.{UPLOAD_TYPES[body.content_type]}"
    form = boards.presigned_upload(key, body.content_type, MAX_UPLOAD_BYTES, UPLOAD_URL_EXPIRY_S)
    return UploadOut(key=key, url=form["url"], fields=form["fields"], max_bytes=MAX_UPLOAD_BYTES)
