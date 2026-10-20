"""
Routes for shots: list, create, read, save, reorder and delete -- always within their scene.

A save carries the version the editor loaded, and is refused with a 409 if the shot has been saved since. Every character and prop a shot's layers show must exist in the project's registries.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError

from taleboard.api.deps import get_boards, get_project, image_urls, not_found
from taleboard.schema.enums import CameraAngle, ShotSize
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, Layer, PropLayer
from taleboard.schema.storyboard import Character, Project, Prop, Scene, Shot
from taleboard.storage.storyboard_store import StoryboardStore


def get_scene(scene_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> Scene:
    """
    Loads the scene a route's path names, or answers 404.

    Arguments:
        scene_id: str - Unique ID of the scene (from the path).
        project: Project - The project (from the path).
        boards: StoryboardStore - Store to read from.

    Returns:
        Scene - The scene.
    """
    try:
        return boards.get_scene(project.project_id, scene_id)
    except KeyError as error:
        raise not_found(error) from None

router = APIRouter(prefix="/projects/{project_id}/scenes/{scene_id}/shots", tags=["shots"])

class ShotIn(BaseModel):
    """
    Request body for creating a shot.

    Attributes:
        description: str - What happens in the shot. Defaults to "".
        duration_s: float - How long the shot lasts (in seconds). Defaults to 2.
        shot_size: ShotSize - Framing of the shot. Defaults to MEDIUM.
        angle: CameraAngle - Camera angle of the shot. Defaults to EYE_LEVEL.
        details: str - Small visible changes to the location in this shot. Defaults to "".
    """
    description: str = Field(default="", max_length=2000)
    duration_s: float = Field(default=2.0, gt=0, le=60)
    shot_size: ShotSize = ShotSize.MEDIUM
    angle: CameraAngle = CameraAngle.EYE_LEVEL
    details: str = Field(default="", max_length=150)

class ShotSave(ShotIn):
    """
    Request body for saving a shot: all its editable fields, plus the version it was loaded at.

    Attributes:
        layers: list[Layer] - The layer graph, bottom to top.
        version: int - The version the editor loaded.
    """
    layers: list[Layer]
    version: int = Field(ge=0)

class ShotOrderIn(BaseModel):
    """
    Request body for reordering a scene's shots.

    Attributes:
        shot_ids: list[str] - Every shot's ID, each exactly once, in the new order.
    """
    shot_ids: list[str]

class ShotOut(Shot):
    """
    A shot, with a download URL for each of its layers' images.

    Attributes:
        image_urls: dict[str,str] - Download URL for each image key in the shot.
    """
    image_urls: dict[str, str] = Field(default_factory=dict)

def _out(boards: StoryboardStore, project: Project, shot: Shot) -> ShotOut:
    """
    Adds download URLs for the images of every layer that has one, groups' children included.

    Arguments:
        boards: StoryboardStore - Store that signs the URLs.
        project: Project - The project.
        shot: Shot - The shot.

    Returns:
        ShotOut - The shot, with its image URLs.
    """
    keys = (getattr(layer, "image", None) for layer in shot.all_layers())  # Text and group layers have no image
    return ShotOut(**shot.model_dump(), image_urls=image_urls(boards, project.project_id, keys))

def _load(boards: StoryboardStore, project: Project, scene: Scene, shot_id: str) -> Shot:
    """
    Loads a shot, or answers 404.

    Arguments:
        boards: StoryboardStore - Store to read from.
        project: Project - The project.
        scene: Scene - The shot's scene.
        shot_id: str - Unique ID of the shot.

    Returns:
        Shot - The shot.
    """
    try:
        return boards.get_shot(project.project_id, scene.id, shot_id)
    except KeyError as error:
        raise not_found(error) from None

def _build(**fields) -> Shot:
    """
    Builds a shot from a request's fields, answering 422 (like any other bad body) if the shot as a whole is invalid -- two layers sharing an ID.

    Arguments:
        fields: dict - The shot's fields.

    Returns:
        Shot - The shot.
    """
    try:
        return Shot(**fields)
    except ValidationError as error:
        raise RequestValidationError(error.errors(include_url=False, include_context=False)) from None

def _check_registries(boards: StoryboardStore, project: Project, shot: Shot) -> None:
    """
    Answers 400 unless every character and prop the shot's layers show exists in the project's registries.

    Arguments:
        boards: StoryboardStore - Store to read from.
        project: Project - The project.
        shot: Shot - The shot to check.
    """
    layers = shot.all_layers()
    for model, layer_type, field in ((Character, CharacterLayer, "character_id"), (Prop, PropLayer, "prop_id")):
        shown = {getattr(layer, field) for layer in layers if isinstance(layer, layer_type)}
        if not shown:
            continue  # Saves the query
        missing = shown - {entry.id for entry in boards.list_entries(project.project_id, model)}
        if missing:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"There's no {model.__name__.lower()} {', '.join(sorted(missing))} in this project")

@router.get("", response_model=list[ShotOut])
def list_shots(project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> list[ShotOut]:
    """
    Lists the scene's shots, in order.
    """
    return [_out(boards, project, shot) for shot in boards.list_shots(project.project_id, scene.id)]

@router.post("", status_code=status.HTTP_201_CREATED, response_model=ShotOut)
def create_shot(body: ShotIn, project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> ShotOut:
    """
    Adds a shot at the end of the scene, holding just a background layer (not yet generated).
    """
    existing = boards.list_shots(project.project_id, scene.id)
    order = max((s.order for s in existing), default=-1) + 1
    shot = Shot(scene_id=scene.id, order=order, layers=[BackgroundLayer(name="Background")], **body.model_dump())
    boards.create_shot(project.project_id, shot)
    return _out(boards, project, shot)

@router.put("/order", response_model=list[ShotOut])
def reorder_shots(body: ShotOrderIn, project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> list[ShotOut]:
    """
    Puts the scene's shots in a new order -- given as the full list of their IDs -- and renumbers them from 0. Each shot that moves is saved, so its version goes up.
    """
    shots = {shot.id: shot for shot in boards.list_shots(project.project_id, scene.id)}
    if len(body.shot_ids) != len(set(body.shot_ids)) or set(body.shot_ids) != set(shots):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "shot_ids must list every shot in the scene exactly once")
    reordered = []
    for order, shot_id in enumerate(body.shot_ids):
        shot = shots[shot_id]
        if shot.order != order:
            shot = boards.save_shot(project.project_id, shot.model_copy(update={"order": order}))
        reordered.append(_out(boards, project, shot))
    return reordered

@router.get("/{shot_id}", response_model=ShotOut)
def read_shot(shot_id: str, project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> ShotOut:
    """
    Gets one shot.
    """
    return _out(boards, project, _load(boards, project, scene, shot_id))

@router.put("/{shot_id}", response_model=ShotOut)
def save_shot(shot_id: str, body: ShotSave, project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> ShotOut:
    """
    Replaces the shot's editable fields and layers -- refused with a 409 if it has been saved since the version sent. Returns it with its new version.
    """
    current = _load(boards, project, scene, shot_id)
    shot = _build(id=shot_id, scene_id=scene.id, order=current.order, **body.model_dump())
    _check_registries(boards, project, shot)
    try:
        saved = boards.save_shot(project.project_id, shot)
    except KeyError as error:  # Deleted since it was loaded above
        raise not_found(error) from None
    return _out(boards, project, saved)

@router.delete("/{shot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shot(shot_id: str, project: Project = Depends(get_project), scene: Scene = Depends(get_scene), boards: StoryboardStore = Depends(get_boards)) -> Response:
    """
    Deletes a shot. It can't be undone.
    """
    _load(boards, project, scene, shot_id)  # A 404 if there's no such shot
    boards.delete_shot(project.project_id, scene.id, shot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)