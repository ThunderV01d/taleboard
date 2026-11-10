"""
Routes for projects: create, list, read, rename and delete.

A project comes back saying what the signed-in user may do with it (access): "owner" for their own, or the role it was
shared with them at -- so the editor knows to open it read-only.
"""
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from taleboard.api.deps import ProjectAccess, get_boards, get_owned_project, get_project_access, get_user_id
from taleboard.schema.storyboard import Project
from taleboard.storage.storyboard_store import StoryboardStore

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    """
    Request body for creating or renaming a project.

    Attributes:
        name: str - Name of the project.
    """
    name: str = Field(min_length=1, max_length=200)

class ProjectOut(Project):
    """
    A project, with what the signed-in user may do with it.

    Attributes:
        access: Literal["owner","editor","viewer"] - Their access: their own project, or the role it's shared with them at.
    """
    access: Literal["owner", "editor", "viewer"]

@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectOut)
def create_project(body: ProjectIn, user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> ProjectOut:
    """
    Creates an empty project, owned by the signed-in user.

    Arguments:
        body: ProjectIn - The project's name.
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to write to.

    Returns:
        ProjectOut - The new project.
    """
    return ProjectOut(**boards.create_project(body.name, user_id).model_dump(), access="owner")

@router.get("", response_model=list[ProjectOut])
def list_projects(user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> list[ProjectOut]:
    """
    Lists the signed-in user's own projects, newest first, then the projects shared with them, most recently shared first.

    Arguments:
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to read from.

    Returns:
        list[ProjectOut] - Every project they can open, each with their access to it.
    """
    owned = [ProjectOut(**project.model_dump(), access="owner") for project in boards.list_projects(user_id)]
    shared = [ProjectOut(**project.model_dump(), access=share.role.value) for project, share in boards.list_shared_with(user_id)]
    return owned + shared

@router.get("/{project_id}", response_model=ProjectOut)
def read_project(access: ProjectAccess = Depends(get_project_access)) -> ProjectOut:
    """
    Gets one project.

    Arguments:
        access: ProjectAccess - The project the path names (a 404 if it doesn't exist, or isn't theirs or shared with them), and their access to it.

    Returns:
        ProjectOut - The project.
    """
    return ProjectOut(**access.project.model_dump(), access=access.role)

@router.patch("/{project_id}", response_model=ProjectOut)
def rename_project(body: ProjectIn, access: ProjectAccess = Depends(get_project_access), boards: StoryboardStore = Depends(get_boards)) -> ProjectOut:
    """
    Renames a project.

    Arguments:
        body: ProjectIn - The project's new name.
        access: ProjectAccess - The project the path names (a 404 if it doesn't exist, or isn't theirs or shared with them), and their access to it (at least editor).
        boards: StoryboardStore - Store to write to.

    Returns:
        ProjectOut - The renamed project.
    """
    return ProjectOut(**boards.rename_project(access.project.project_id, body.name).model_dump(), access=access.role)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project: Project = Depends(get_owned_project), boards: StoryboardStore = Depends(get_boards)) -> Response:
    """
    Deletes a project and everything in it -- its registries, scenes, shots, images and shares. It can't be undone, so only its owner can.

    Arguments:
        project: Project - The project the path names (a 404 if it doesn't exist, or isn't theirs or shared with them; a 403 unless it's theirs).
        boards: StoryboardStore - Store to delete from.

    Returns:
        Response - An empty 204.
    """
    boards.delete_project(project.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)