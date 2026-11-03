"""
Routes for generation: see what a Generate request would draw, ask for it, and follow its job.

A request names what to draw by how far it reaches: nothing for the whole project, a scene, a shot, or one layer. Its layers are worked out when it's asked for, and saved as the job's tasks; the job then waits its turn behind the project's earlier jobs.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator

from taleboard.api.deps import get_boards, get_generation_queue, get_project, not_found
from taleboard.generation.planning import Planned, images_at_most, layers_to_draw
from taleboard.jobs.queue import GenerationQueue
from taleboard.schema.base import Model
from taleboard.schema.generation import GenerationJob, GenerationTask
from taleboard.schema.layers import GeneratedLayer
from taleboard.schema.storyboard import Character, Location, Project, Prop
from taleboard.storage.storyboard_store import StoryboardStore

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])


class GenerateIn(BaseModel):
    """
    Request body naming what to draw: leave everything out for the whole project, or narrow it to a scene, a shot in it, or one layer of that shot.

    Attributes:
        scene_id: str - Draw only this scene. Defaults to None (the whole project).
        shot_id: str - Draw only this shot (of scene_id). Defaults to None.
        layer_id: str - Draw only this layer (of shot_id) -- drawn even if it's up to date. Defaults to None.
    """
    scene_id: str | None = None
    shot_id: str | None = None
    layer_id: str | None = None

    @model_validator(mode="after")
    def narrower_needs_wider(self) -> "GenerateIn":
        """
        Rejects a shot without its scene, or a layer without its shot -- each is looked up within the one around it.
        """
        if self.shot_id is not None and self.scene_id is None:
            raise ValueError("shot_id needs scene_id")
        if self.layer_id is not None and self.shot_id is None:
            raise ValueError("layer_id needs shot_id")
        return self

class GeneratePlan(Model):
    """
    What a Generate request would draw.

    Attributes:
        layers: int - Layers it would draw.
        images: int - The most images that would take -- fewer, if some are already drawn.
    """
    layers: int
    images: int


def _plan(body: GenerateIn, project: Project, boards: StoryboardStore) -> list[Planned]:
    """
    The layers a request would draw, in order -- or a 404 for anything it names that doesn't exist, and a 400 for a layer that isn't generated.
    """
    pid = project.project_id
    try:
        if body.scene_id is None:
            scenes = boards.list_scenes(pid)
        else:
            scenes = [boards.get_scene(pid, body.scene_id)]
        if body.shot_id is None:
            shots = [(scene, shot) for scene in scenes for shot in boards.list_shots(pid, scene.id)]
        else:
            shots = [(scenes[0], boards.get_shot(pid, scenes[0].id, body.shot_id))]
    except KeyError as error:
        raise not_found(error) from None

    if body.layer_id is None:
        return layers_to_draw(shots)
    scene, shot = shots[0]
    layer = next((l for l in shot.all_layers() if l.id == body.layer_id), None)
    if layer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No layer {body.layer_id!r} in shot {shot.id!r}")
    if not isinstance(layer, GeneratedLayer):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"A {layer.type} layer isn't generated")
    return [Planned(scene, shot, layer)]


@router.post("/generate/preview", response_model=GeneratePlan)
def preview_generation(body: GenerateIn, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> GeneratePlan:
    """
    Says how many layers a Generate request would draw, and at most how many images that would take -- without drawing anything.
    """
    planned = _plan(body, project, boards)
    pid = project.project_id
    images = images_at_most(
        planned,
        {entry.id: entry for entry in boards.list_entries(pid, Location)},
        {entry.id: entry for entry in boards.list_entries(pid, Character)},
        {entry.id: entry for entry in boards.list_entries(pid, Prop)},
    )
    return GeneratePlan(layers=len(planned), images=images)


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED, response_model=GenerationJob)
def generate(
    body: GenerateIn,
    project: Project = Depends(get_project),
    boards: StoryboardStore = Depends(get_boards),
    queue: GenerationQueue = Depends(get_generation_queue),
) -> GenerationJob:
    """
    Asks for the layers a request names to be drawn: saves them as a job's tasks, and queues it behind the project's earlier jobs. A request with nothing to draw is a 400, and no job is made.
    """
    planned = _plan(body, project, boards)
    if not planned:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to draw -- every layer is up to date")
    job = GenerationJob(
        created_at=datetime.now(timezone.utc),
        tasks=[GenerationTask(scene_id=p.scene.id, shot_id=p.shot.id, layer_id=p.layer.id) for p in planned],
    )
    boards.create_job(project.project_id, job)  # Saved before it's queued, so the worker always finds it
    queue.enqueue(project.project_id, job.id)
    return job


@router.get("/jobs", response_model=list[GenerationJob])
def list_jobs(project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> list[GenerationJob]:
    """
    Lists the project's generation jobs, newest first -- so a reopened editor can pick up the ones still running.
    """
    return boards.list_jobs(project.project_id)


@router.get("/jobs/{job_id}", response_model=GenerationJob)
def read_job(job_id: str, project: Project = Depends(get_project), boards: StoryboardStore = Depends(get_boards)) -> GenerationJob:
    """
    Gets one generation job, with how each of its layers went.
    """
    try:
        return boards.get_job(project.project_id, job_id)
    except KeyError as error:
        raise not_found(error) from None