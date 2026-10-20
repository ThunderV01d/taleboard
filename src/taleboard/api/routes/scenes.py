"""
Routes for scenes: list, create, read, edit, reorder and delete.

A scene's location must exist in the project's registry -- it's checked whenever a scene is created or moved, so a scene can never point at nothing. Deleting a scene deletes all its shots.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from taleboard.api.deps import get_boards, get_project, not_found
from taleboard.schema.enums import Atmosphere, TimeOfDay
from taleboard.schema.storyboard import Location, Project, Scene
from taleboard.storage.storyboard_store import StoryboardStore

router = APIRouter(prefix="/projects/{project_id}/scenes", tags=["scenes"])


class SceneIn(BaseModel):
    """
    Request body for creating a scene.

    Attributes:
        name: str - Name of the scene. Defaults to "".
        description: str - What happens in the scene. Defaults to "".
        location_id: str - The location (in the project's registry) the scene takes place in.
        time_of_day: TimeOfDay - Time of day. Defaults to DAY.
        atmosphere: Atmosphere - Weather and atmosphere. Defaults to CLEAR.
    """
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    location_id: str
    time_of_day: TimeOfDay = TimeOfDay.DAY
    atmosphere: Atmosphere = Atmosphere.CLEAR

class ScenePatch(BaseModel):
    """
    Request body for editing a scene. Only the fields sent are changed.

    Attributes:
        name: str - New name. Defaults to None (unchanged).
        description: str - New description. Defaults to None (unchanged).
        location_id: str - New location. Defaults to None (unchanged).
        time_of_day: TimeOfDay - New time of day. Defaults to None (unchanged).
        atmosphere: Atmosphere - New atmosphere. Defaults to None (unchanged).
    """
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    location_id: str | None = None
    time_of_day: TimeOfDay | None = None
    atmosphere: Atmosphere | None = None

class SceneOrderIn(BaseModel):
    """
    Request body for reordering a project's scenes.

    Attributes:
        scene_ids: list[str] - Every scene's ID, each exactly once, in the new order.
    """
    scene_ids: list[str]


def _check_location(boards: StoryboardStore, project: Project, location_id: str) -> None:
    """
    Answers 400 unless the location exists in the project's registry.

    Arguments:
        boards: StoryboardStore - Store to read from.
        project: Project - The project.
        location_id: str - Unique ID of the location.
    """
    try:
        boards.get_entry(project.project_id, Location, location_id)
    except KeyError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"There's no location {location_id!r} in this project") from None

def _load(boards: StoryboardStore, project: Project, scene_id: str) -> Scene:
    """
    Loads a scene, or answers 404.

    Arguments:
        boards: StoryboardStore - Store to read from.
        project: Project - The project.
        scene_id: str - Unique ID of the scene.

    Returns:
        Scene - The scene.
    """
    try:
        return boards.get_scene(project.project_id, scene_id)
    except KeyError as error:
        raise not_found(error) from None


@router.get("", response_model=list[Scene])
def list_scenes(project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> list[Scene]:
    """
    Lists the project's scenes, in story order.
    """
    return boards.list_scenes(project.project_id)

@router.post("", status_code=status.HTTP_201_CREATED, response_model=Scene)
def create_scene(body: SceneIn, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Scene:
    """
    Adds a scene at the end of the project, in a location that must already exist.
    """
    _check_location(boards, project, body.location_id)
    existing = boards.list_scenes(project.project_id)
    scene = Scene(**body.model_dump(), order=max((s.order for s in existing), default=-1) + 1)
    boards.create_scene(project.project_id, scene)
    return scene

@router.put("/order", response_model=list[Scene])
def reorder_scenes(body: SceneOrderIn, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> list[Scene]:
    """
    Puts the project's scenes in a new order -- given as the full list of their IDs -- and renumbers them from 0.
    """
    scenes = {scene.id: scene for scene in boards.list_scenes(project.project_id)}
    if len(body.scene_ids) != len(set(body.scene_ids)) or set(body.scene_ids) != set(scenes):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scene_ids must list every scene in the project exactly once")
    reordered = []
    for order, scene_id in enumerate(body.scene_ids):
        scene = scenes[scene_id]
        if scene.order != order:
            scene = scene.model_copy(update={"order": order})
            boards.save_scene(project.project_id, scene)
        reordered.append(scene)
    return reordered

@router.get("/{scene_id}", response_model=Scene)
def read_scene(scene_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Scene:
    """
    Gets one scene.
    """
    return _load(boards, project, scene_id)

@router.patch("/{scene_id}", response_model=Scene)
def edit_scene(scene_id: str, body: ScenePatch, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Scene:
    """
    Changes the fields sent. Moving a scene to another location (which must exist), or changing its lighting, leaves its backgrounds needing regeneration.
    """
    scene = _load(boards, project, scene_id)
    changes = body.model_dump(exclude_none=True)
    if "location_id" in changes:
        _check_location(boards, project, changes["location_id"])
    edited = scene.model_copy(update=changes)
    boards.save_scene(project.project_id, edited)
    return edited

@router.delete("/{scene_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scene(scene_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Response:
    """
    Deletes a scene and all its shots. It can't be undone.
    """
    _load(boards, project, scene_id)  # A 404 if there's no such scene
    boards.delete_scene(project.project_id, scene_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
