"""
What every API route shares: the store, who's asking (and whether it's the guest), the project a path names and what
they may do with it, and turning S3 keys into download URLs.

Permissions are decided in one place, get_project_access, which every project-scoped route depends on (directly, or
through get_project or get_owned_project): reading (GET) needs at least viewer, anything else needs at least editor,
and someone with no access at all gets the same 404 as for a missing project. The guest is refused every change
outright, by refuse_guest_writes, whatever it has been granted -- so it can never create a project of its own (and
spend money as its owner).

Attributes:
    IMAGE_URL_EXPIRY_S: int - How long the image URLs handed to clients stay valid (in seconds).
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status

from taleboard.auth.guest_session import GUEST_GROUP
from taleboard.jobs.queue import GenerationQueue
from taleboard.schema.sharing import ACCESS_RANK, Access
from taleboard.schema.storyboard import Project
from taleboard.storage.storyboard_store import StoryboardStore

IMAGE_URL_EXPIRY_S = 3600

# Methods that only read -- every other method changes something
READ_METHODS = frozenset({"GET", "HEAD"})


@lru_cache
def get_boards() -> StoryboardStore:
    """
    Connects to the store once per container, so warm invocations reuse the connection.

    Returns:
        StoryboardStore - Store configured from the environment.
    """
    return StoryboardStore.from_env()

@lru_cache
def get_generation_queue() -> GenerationQueue:
    """
    Connects to the generation job queue once per container.

    Returns:
        GenerationQueue - Queue configured from the environment.
    """
    return GenerationQueue.from_env()

def get_claims(request: Request) -> dict:
    """
    The claims of the token API Gateway's JWT authorizer has already verified.

    The Lambda can trust these claims because only API Gateway invokes it, and only after checking the token's signature, expiry and app client. Fails closed: a request that arrives without verified claims (eg:- a route left without the authorizer) is refused rather than treated as anyone.

    Arguments:
        request: Request - The request (Mangum puts the Lambda event in its scope).

    Returns:
        dict - The claims.
    """
    try:
        claims = request.scope["aws.event"]["requestContext"]["authorizer"]["jwt"]["claims"]
        claims["sub"]
    except (KeyError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"}) from None
    return claims

def get_user_id(claims: dict = Depends(get_claims)) -> str:
    """
    The signed-in user's ID -- their token's sub claim.

    Arguments:
        claims: dict - The verified token's claims.

    Returns:
        str - The user's ID.
    """
    return claims["sub"]

def is_guest(claims: dict = Depends(get_claims)) -> bool:
    """
    Whether the request comes from the shared guest user: a token from the guest app client, or one carrying the guests group.

    Either is enough, so the guest is caught even if it were ever signed in some other way. API Gateway passes a list claim as a string ("[guests other]"), so the group is looked for in either form.

    Arguments:
        claims: dict - The verified token's claims.

    Returns:
        bool - True for the guest.
    """
    guest_client = os.environ.get("TALEBOARD_GUEST_CLIENT_ID")
    if guest_client and claims.get("client_id") == guest_client:
        return True
    groups = claims.get("cognito:groups", [])
    if isinstance(groups, str):
        groups = groups.strip("[]").replace(",", " ").split()
    return GUEST_GROUP in groups

def refuse_guest_writes(request: Request, guest: bool = Depends(is_guest)) -> None:
    """
    Refuses the guest anything but reading, on every route -- the guest's hard lock, whatever it has been shared.

    Applied to the whole app, so it also covers routes that aren't about one project (creating a project, above all: the guest would own it, and could then generate in it).

    Arguments:
        request: Request - The request.
        guest: bool - Whether it's the guest asking.
    """
    if guest and request.method not in READ_METHODS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Guests can look around but not change anything -- sign up to make your own storyboards")

def get_role(boards: StoryboardStore, user_id: str, project: Project) -> Access:
    """
    What a user may do with a project: its owner owns it, and anyone else has whatever role a share gives them -- or none.

    Arguments:
        boards: StoryboardStore - Store to read shares from.
        user_id: str - The user.
        project: Project - The project.

    Returns:
        Access - "owner", "editor", "viewer" or "none".
    """
    if project.owner_id == user_id:
        return "owner"
    share = boards.get_share(project.project_id, user_id)
    return share.role.value if share else "none"

@dataclass(frozen=True)
class ProjectAccess:
    """
    The project a route's path names, and what the signed-in user may do with it.

    Attributes:
        project: Project - The project.
        role: Access - Their access to it (never "none" -- that's a 404).
    """
    project: Project
    role: Access

def get_project_access(request: Request, project_id: str, user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> ProjectAccess:
    """
    Loads the project a route's path names and checks the user may do what the request asks -- the one place every project-scoped route's permissions are decided.

    Reading (GET) needs at least viewer; anything else (every write, upload and generation) needs at least editor. A project the user has no access to is a 404, the same as a missing one, so its existence can't be confirmed; one they can see but not change is a 403.

    Arguments:
        request: Request - The request (its method says whether it only reads).
        project_id: str - Unique project ID (from the path).
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to read from.

    Returns:
        ProjectAccess - The project, and the user's role.
    """
    try:
        project = boards.get_project(project_id)
    except KeyError:
        project = None
    role = get_role(boards, user_id, project) if project else "none"
    if project is None or role == "none":  # One answer for both, so the two can't be told apart
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project with ID {project_id!r}")
    needed = "viewer" if request.method in READ_METHODS else "editor"
    if ACCESS_RANK[role] < ACCESS_RANK[needed]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This project is shared with you to view only")
    return ProjectAccess(project, role)

def get_project(access: ProjectAccess = Depends(get_project_access)) -> Project:
    """
    The project a route's path names, once get_project_access has checked the user may do what the request asks.

    Arguments:
        access: ProjectAccess - The project, and the user's role.

    Returns:
        Project - The project.
    """
    return access.project

def get_owned_project(access: ProjectAccess = Depends(get_project_access)) -> Project:
    """
    The project a route's path names, for routes only its owner may use (sharing it) -- a 403 to anyone it's shared with.

    Arguments:
        access: ProjectAccess - The project, and the user's role.

    Returns:
        Project - The project.
    """
    if access.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project's owner can do that")
    return access.project

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
