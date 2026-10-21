"""
Routes for projects: create, list, read, rename and delete.
"""
from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from taleboard.api.deps import get_boards, get_project, get_user_id
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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Project)
def create_project(body: ProjectIn, user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> Project:
    """
    Creates an empty project, owned by the signed-in user.

    Arguments:
        body: ProjectIn - The project's name.
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to write to.

    Returns:
        Project - The new project.
    """
    return boards.create_project(body.name, user_id)

@router.get("", response_model=list[Project])
def list_projects(user_id: str = Depends(get_user_id), boards: StoryboardStore = Depends(get_boards)) -> list[Project]:
    """
    Lists the signed-in user's projects, newest first.

    Arguments:
        user_id: str - The signed-in user.
        boards: StoryboardStore - Store to read from.

    Returns:
        list[Project] - Every project.
    """
    return boards.list_projects(user_id)

@router.get("/{project_id}", response_model=Project)
def read_project(project: Project = Depends(get_project)) -> Project:
    """
    Gets one project.

    Arguments:
        project: Project - The project the path names (a 404 if it doesn't exist).

    Returns:
        Project - The project.
    """
    return project

@router.patch("/{project_id}", response_model=Project)
def rename_project(body: ProjectIn, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Project:
    """
    Renames a project.

    Arguments:
        body: ProjectIn - The project's new name.
        project: Project - The project the path names (a 404 if it doesn't exist).
        boards: StoryboardStore - Store to write to.

    Returns:
        Project - The renamed project.
    """
    return boards.rename_project(project.project_id, body.name)

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Response:
    """
    Deletes a project and everything in it -- its registries, scenes, shots and images. It can't be undone.

    Arguments:
        project: Project - The project the path names (a 404 if it doesn't exist).
        boards: StoryboardStore - Store to delete from.

    Returns:
        Response - An empty 204.
    """
    boards.delete_project(project.project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
