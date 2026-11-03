"""
Routes for importing a story into a project: the story is saved, and an import job queued to break it down into the project's registries, scenes and shots (and, if asked, to draw them all after).

The job is followed like any other, through the generation routes' GET /jobs.

Attributes:
    MAX_STORY_LENGTH: int - Longest story accepted, in characters (it's stored as one DynamoDB item, at most 400 KB).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from taleboard.api.deps import get_boards, get_generation_queue, get_project
from taleboard.jobs.queue import GenerationQueue
from taleboard.schema.generation import GenerationJob, JobKind, JobStatus
from taleboard.schema.storyboard import Character, Location, Project, Prop
from taleboard.storage.storyboard_store import StoryboardStore

MAX_STORY_LENGTH = 50_000

router = APIRouter(prefix="/projects/{project_id}", tags=["imports"])


class ImportIn(BaseModel):
    """
    Request body for a story import.

    Attributes:
        story: str - The story (in plain text, paragraphs separated by blank lines).
        draw: bool - Whether to draw every layer once it's imported. Defaults to True.
    """
    story: str = Field(min_length=1, max_length=MAX_STORY_LENGTH)
    draw: bool = True

    @field_validator("story")
    @classmethod
    def has_words(cls, story: str) -> str:
        """
        Rejects a story that's only whitespace.
        """
        if not story.strip():
            raise ValueError("The story is empty")
        return story


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, response_model=GenerationJob)
def import_story(
    body: ImportIn,
    project: Project = Depends(get_project),
    boards: StoryboardStore = Depends(get_boards),
    queue: GenerationQueue = Depends(get_generation_queue),
) -> GenerationJob:
    """
    Queues a story to be imported into an empty project. A project with anything in it already -- or an import already on its way -- is a 409, as an import fills the project from scratch.
    """
    pid = project.project_id
    if any(job.kind == JobKind.IMPORT and job.status in (JobStatus.QUEUED, JobStatus.RUNNING) for job in boards.list_jobs(pid)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A story is already being imported into this project")
    if boards.list_scenes(pid) or any(boards.list_entries(pid, model) for model in (Character, Prop, Location)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A story can only be imported into an empty project")

    job = GenerationJob(created_at=datetime.now(timezone.utc), kind=JobKind.IMPORT, draw=body.draw)
    boards.save_story(pid, job.id, body.story)  # Saved before the job, and both before it's queued, so the worker always finds them
    boards.create_job(pid, job)
    queue.enqueue(pid, job.id, JobKind.IMPORT)
    return job
