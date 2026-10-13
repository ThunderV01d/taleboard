"""
TaleBoard's HTTP API -- creates projects, accepts stories, and reports render progress.

Submitting a story stores it and queues a render job, then returns 202 straight away. The worker Lambda (taleboard.jobs.worker) does the rendering, saving each shot as it finishes. Clients poll the status endpoint and read shots as they appear.

Imports nothing from taleboard.rendering -- loading the image models would add seconds to every cold start of the API Lambda.

Every endpoint requires the shared X-API-Key header (see verify_api_key). It's a cost guard against stray visitors and bots, not real authentication -- the frontend ships the key in its JavaScript.

Attributes:
    IMAGE_URL_EXPIRY_S: int - How long the image URLs handed to clients stay valid (in seconds).
    API_KEY_HEADER: str - Header clients send the shared API key in.
    API_KEY_PARAMETER_ENV: str - Environment variable naming the SSM parameter that holds the key.
    app: FastAPI - The FastAPI application.
    handler: Mangum - API Lambda entry point -- adapts API Gateway (HTTP API, payload v2.0) events to the app.
"""
import hmac
import os
import uuid
from datetime import datetime
from functools import lru_cache
import boto3
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from mangum import Mangum

from taleboard.jobs.queue import JobQueue
from taleboard.schema.enums import CameraAngle, ProjectStatus, ShotSize
from taleboard.schema.models import Project, Region, Shot
from taleboard.storage.project_store import SHOT_INDEX_WIDTH, ProjectStore

IMAGE_URL_EXPIRY_S = 3600

API_KEY_HEADER = "X-API-Key"
API_KEY_PARAMETER_ENV = "TALEBOARD_API_KEY_PARAMETER"

@lru_cache
def get_api_key() -> str:
    """
    Reads the shared API key from SSM Parameter Store once per container, so warm invocations never call SSM.

    Fails closed: if the parameter isn't configured, every request errors rather than going through unchecked.

    Returns:
        str - The expected API key.
    """
    return boto3.client("ssm").get_parameter(Name=os.environ[API_KEY_PARAMETER_ENV], WithDecryption=True)["Parameter"]["Value"]

def verify_api_key(
    api_key: str | None = Security(APIKeyHeader(name=API_KEY_HEADER, auto_error=False)),
    expected: str = Depends(get_api_key),
) -> None:
    """
    Rejects a request unless it carries the shared API key. Applied to every endpoint.

    Arguments:
        api_key: str - The key the client sent, if any.
        expected: str - The key it must match.

    Raises:
        HTTPException - 401 if the key is missing or wrong.
    """
    if api_key is None or not hmac.compare_digest(api_key.encode(), expected.encode()):  # Constant-time, so response timing doesn't leak the key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key", headers={"WWW-Authenticate": "APIKey"})

app = FastAPI(title="TaleBoard API", dependencies=[Depends(verify_api_key)])

@lru_cache
def get_store() -> ProjectStore:
    """
    Connects to the store once per container, so warm invocations reuse the connection.

    Returns:
        ProjectStore - Store configured from the environment.
    """
    return ProjectStore.from_env()

@lru_cache
def get_queue() -> JobQueue:
    """
    Connects to the job queue once per container, so warm invocations reuse the connection.

    Returns:
        JobQueue - Queue configured from the environment.
    """
    return JobQueue.from_env()

class ProjectIn(BaseModel):
    """
    Request body for creating a project.

    Attributes:
        name: str - Name of the project.
    """
    name: str = Field(min_length=1, max_length=200)

class StoryIn(BaseModel):
    """
    Request body for submitting a story.
    
    Attributes:
        story: str - The story (in plain text). Paragraphs are separated by blank lines.
    """
    story: str = Field(max_length=100_000)

    @field_validator("story")
    @classmethod
    def story_not_blank(cls, value: str) -> str:
        """
        Rejects an empty or whitespace-only story before anything is stored or queued.

        Raises a ValueError if the story is empty.

        Arguments:
            value: str - The submitted story.

        Returns:
            str - The story, unchanged.
        """
        if not value.strip():
            raise ValueError("story must not be empty")
        return value

class ProjectOut(BaseModel):
    """
    A project's metadata and render job state.

    Attributes:
        project_id: str - Unique project ID.
        name: str - Name of the project.
        created_at: datetime - When the project was created (UTC).
        status: ProjectStatus - Where the project's render job is.
        shot_count: int - Number of shots, once the breakdown is final.
        error: str - Why the render job failed (if it failed).
    """
    project_id: str
    name: str
    created_at: datetime
    status: ProjectStatus
    shot_count: int | None
    error: str | None

class JobAccepted(BaseModel):
    """
    Response to a submitted story.

    Attributes:
        job_id: str - Unique render job ID.
        status_url: str - Where to poll the job's progress.
    """
    job_id: str
    status_url: str

class StatusOut(BaseModel):
    """
    A render job's progress.
    
    Attributes:
        status: ProjectStatus - Where the project's render job is.
        total_shots: int - Number of shots, once the breakdown is final.
        rendered_shots: int - Number of shots rendered so far.
        shots_needing_review: int - Number of rendered shots a human should look at.
        error: str - Why the render job failed.
    """
    status: ProjectStatus
    total_shots: int | None
    rendered_shots: int
    shots_needing_review: int
    error: str | None

class ShotOut(BaseModel):
    """
    One shot, as clients see it.

    Attributes:
        shot_id: str - The shot's position in the story, zero-padded (eg:- "0007").
        description: str - What happens in the shot.
        setting: str - The shot's location and environment.
        shot_size: ShotSize - Framing of the shot.
        angle: CameraAngle - Camera angle of the shot.
        duration_s: float - How long the shot lasts (in seconds).
        paragraph_index: int - Paragraph of the story the shot came from.
        regions: list[Region] - Where each character is palced.
        rendered: bool - Whether the shot's image is ready.
        needs_review: bool - Whether a human should look at the shot.
        image_key: str - S3 key of the composited image, once rendered.
        image_url: str - Temporary download URL for the composited image, once rendered.
    """
    shot_id: str
    description: str
    setting: str
    shot_size: ShotSize
    angle: CameraAngle
    duration_s: float
    paragraph_index: int
    regions: list[Region]
    rendered: bool
    needs_review: bool
    image_key: str | None
    image_url: str | None

class CharacterOut(BaseModel):
    """
    One character, as clients see them.
    
    Attributes:
        character_id: str - Unique character ID.
        name: str - Full name of the character.
        description: str - Visual description of the character.
        aliases: list[str] - Other ways the story refers to the character.
        appearance_reference: str - S3 key of the character's reference image, once generated.
        appearance_reference_url: str - Temporary download URL for the chracter's reference image, once generated.
    """
    character_id: str
    name: str
    description: str
    aliases: list[str]
    appearance_reference: str | None
    appearance_reference_url: str | None

def _project_or_404(store: ProjectStore, project_id: str) -> Project:
    """
    Gets a project's metadata, or responds 404.
    
    Arguments:
        store: ProjectStore - Store to read from.
        project_id: str - Unique project ID.
    
    Returns:
        Project - The project (without shots or cast).
    """
    try:
        return store.get_project(project_id)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No project with ID {project_id!r}") from None

def _project_out(project: Project) -> ProjectOut:
    """
    Converts a Project into its response object.

    Arguments:
        project: Project - The project.

    Returns:
        ProjectOut - The project's metadata and job state.
    """
    return ProjectOut.model_validate(project.model_dump(include=set(ProjectOut.model_fields)))

def _shot_out(store: ProjectStore, index: int, shot: Shot) -> ShotOut:
    """
    Converts a Shot into its response shape, with a download URL if it's rendered.

    Arguments:
        store: ProjectStore - Store used to build the download URL.
        index: int - Position of the shot in the story (0-indexed).
        shot: Shot - The shot.

    Returns:
        ShotOut - The shot, as clients see it.
    """
    return ShotOut(
        shot_id=f"{index:0{SHOT_INDEX_WIDTH}d}",
        **shot.model_dump(include={"description","setting","shot_size","angle","duration_s","paragraph_index","regions","needs_review"}),
        rendered=shot.generated_frame is not None,
        image_key=shot.generated_frame,
        image_url=store.presigned_url(shot.generated_frame, IMAGE_URL_EXPIRY_S) if shot.generated_frame else None
    )

@app.post("/projects",status_code=status.HTTP_201_CREATED,response_model=ProjectOut)
def create_project(body: ProjectIn, store: ProjectStore = Depends(get_store)) -> ProjectOut:
    """
    Creates an empty project.

    Arguments:
        body: ProjectIn - The project's name.
        store: ProjectStore - Store to write to.

    Returns:
        ProjectOut - A new project.
    """
    return _project_out(store.create_project(body.name))

@app.get("/projects",response_model=list[ProjectOut])
def list_projects(store: ProjectStore = Depends(get_store)) -> list[ProjectOut]:
    """
    Lists every project, newest first.
    
    Arguments:
        store: ProjectStore - Store to read from.

    Returns:
        list[ProjectOut] - Every project's metadata.
    """
    return [_project_out(project) for project in store.list_projects()]


@app.get("/projects/{project_id}",response_model=ProjectOut)
def get_project(project_id: str, store: ProjectStore = Depends(get_store)) -> ProjectOut:
    """
    Gets one project's metadata and render job state.

    Arguments:
        project_id: str - Unique project ID.
        store: ProjectStore - Store to read from.

    Returns:
        ProjectOut - The project.
    """
    return _project_out(_project_or_404(store,project_id))

@app.post("/projects/{project_id}/story",status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
def submit_story(project_id: str, body: StoryIn, store: ProjectStore = Depends(get_store), queue: JobQueue = Depends(get_queue)) -> JobAccepted:
    """
    Stores a story and queues its render job, returning straight away -- rendering happens in the worker.

    Arguments:
        project_id: str - Unique project ID.
        body: StoryIn - The story.
        store: ProjectStore - Store to write to.
        queue: JobQueue - Queue to put the render job on.

    Returns:
        JobAccepted - The job's ID, and where to poll its progress.
    """
    _project_or_404(store,project_id)
    job_id = uuid.uuid4().hex
    try:
        store.submit_story(project_id,job_id,body.story)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None

    try:
        queue.enqueue(project_id, job_id)
    except Exception:
        # Without this, the project would sit at "pending" forever with no job to run it
        # Failing it lets the client resubmit
        store.finish_job(project_id, job_id, ProjectStatus.FAILED, error="Could not queue the render job")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not queue the render job -- please submit the story again") from None
    return JobAccepted(job_id=job_id, status_url=f"/projects/{project_id}/status")


@app.get("/projects/{project_id}/status", response_model=StatusOut)
def get_status(project_id: str, store: ProjectStore = Depends(get_store)) -> StatusOut:
    """
    Reports a render job's progress. Progress is read from the shots themselves -- the same record the worker resumes from.
    Arguments:
        project_id: str - Unique project ID.
        store: ProjectStore - Store to read from.
    Returns:
        StatusOut - The job's progress.
    """
    project = _project_or_404(store, project_id)
    shots = store.list_shots(project_id) if project.shot_count is not None else []  # Shots without a shot_count are an unfinished breakdown, not progress
    return StatusOut(
        status=project.status,
        total_shots=project.shot_count,
        rendered_shots=sum(1 for shot in shots if shot.generated_frame is not None),
        shots_needing_review=sum(1 for shot in shots if shot.needs_review),
        error=project.error,
    )
@app.get("/projects/{project_id}/shots", response_model=list[ShotOut])
def list_shots(project_id: str, store: ProjectStore = Depends(get_store)) -> list[ShotOut]:
    """
    Lists a project's shots in story order -- including unrendered ones while a job is running.
    Arguments:
        project_id: str - Unique project ID.
        store: ProjectStore - Store to read from.
    Returns:
        list[ShotOut] - Every shot so far.
    """
    project = _project_or_404(store, project_id)
    if project.shot_count is None:
        return []
    return [_shot_out(store, index, shot) for index, shot in enumerate(store.list_shots(project_id))]
@app.get("/projects/{project_id}/shots/{shot_id}", response_model=ShotOut)
def get_shot(project_id: str, shot_id: str, store: ProjectStore = Depends(get_store)) -> ShotOut:
    """
    Gets one shot. The shot ID is its position in the story ("7" and "0007" both work).
    Arguments:
        project_id: str - Unique project ID.
        shot_id: str - The shot's position in the story.
        store: ProjectStore - Store to read from.
    Returns:
        ShotOut - The shot.
    """
    project = _project_or_404(store, project_id)
    shot = store.get_shot(project_id, int(shot_id)) if shot_id.isdigit() and project.shot_count is not None else None
    if shot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No shot {shot_id!r} in project {project_id!r}")
    return _shot_out(store, int(shot_id), shot)
@app.get("/projects/{project_id}/characters", response_model=list[CharacterOut])
def list_characters(project_id: str, store: ProjectStore = Depends(get_store)) -> list[CharacterOut]:
    """
    Lists a project's cast, with a download URL for each reference image that has been generated.
    Arguments:
        project_id: str - Unique project ID.
        store: ProjectStore - Store to read from.
    Returns:
        list[CharacterOut] - Every character.
    """
    _project_or_404(store, project_id)
    return [
        CharacterOut(
            character_id=character_id,
            **character.model_dump(),
            appearance_reference_url=store.presigned_url(character.appearance_reference, IMAGE_URL_EXPIRY_S) if character.appearance_reference else None,
        )
        for character_id, character in store.list_characters(project_id).items()
    ]

# lifespan="off": startup/shutdown hooks don't map onto Lambda's invoke model, and the clients they'd create are already cached per container by get_store/get_queue
handler = Mangum(app, lifespan="off")