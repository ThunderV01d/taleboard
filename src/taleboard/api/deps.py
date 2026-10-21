"""
What every API route shares: the store, the project a path names (or a 404), and turning S3 keys into download URLs.

Attributes:
    IMAGE_URL_EXPIRY_S: int - How long the image URLs handed to clients stay valid (in seconds).
"""
from functools import lru_cache
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status

from taleboard.schema.storyboard import Project
from taleboard.storage.storyboard_store import StoryboardStore

IMAGE_URL_EXPIRY_S = 3600


@lru_cache
def get_boards() -> StoryboardStore:
    """
    Connects to the store once per container, so warm invocations reuse the connection.

    Returns:
        StoryboardStore - Store configured from the environment.
    """
    return StoryboardStore.from_env()

def get_user_id(request: Request) -> str:
    """
    The signed-in user's ID -- the sub claim of the token API Gateway's JWT authorizer has already verified.

    The Lambda can trust these claims because only API Gateway invokes it, and only after checking the token's signature, expiry and app client. Fails closed: a request that arrives without verified claims (eg:- a route left without the authorizer) is refused rather than treated as anyone.

    Arguments:
        request: Request - The request (Mangum puts the Lambda event in its scope).

    Returns:
        str - The user's ID.
    """
    try:
        return request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]
    except (KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}) from None

def get_project(project_id: str, user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> Project:
    """
    Loads the project a route's path names, or answers 404 -- so every project-scoped route checks it, and who owns it, in the same place.

    Someone else's project is a 404 too, not a 403: a 403 would confirm that the project exists.

    Arguments:
        project_id: str - Unique project ID (from the path).
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to read from.

    Returns:
        Project - The project.
    """
    try:
        project = boards.get_project(project_id)
    except KeyError:
        project = None
    if project is None or project.owner_id != user_id:  # One answer for both, so the two can't be told apart
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project with ID {project_id!r}")
    return project

def not_found(error: KeyError) -> HTTPException:
    """
    Turns a store's KeyError (something the path named doesn't exist) into a 404, keeping its message.

    Arguments:
        error: KeyError - The store's error.

    Returns:
        HTTPException - A 404 to raise.
    """
    return HTTPException(status.HTTP_404_NOT_FOUND, error.args[0] if error.args else "Not found")

def image_urls(boards: StoryboardStore, project_id: str, keys: Iterable[str | None]) -> dict[str, str]:
    """
    Builds a download URL for each image key -- but only for images belonging to this project.

    Keys inside a shot or registry entry are data the client can edit, so a key pointing into another project (or anywhere else in the bucket) is never signed.

    Arguments:
        boards: StoryboardStore - Store that signs the URLs.
        project_id: str - Unique project ID.
        keys: Iterable[str|None] - Image keys; empty ones (images not made yet) are skipped.

    Returns:
        dict[str,str] - Download URL for each of the project's keys.
    """
    prefix = f"projects/{project_id}/"
    return {key: boards.presigned_url(key, IMAGE_URL_EXPIRY_S) for key in set(keys) if key and key.startswith(prefix)}
