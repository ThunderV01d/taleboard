"""
Defines generation jobs: the layers one Generate request is to draw, and how each of them went.

A job is expanded into its tasks when it's asked for -- one per layer -- and the worker works through them in order, recording each result on its task as it goes. A project's jobs run one at a time, in the order they were asked for, so an image one job draws is already there for the next.
"""
import uuid
from datetime import datetime
from enum import Enum

from pydantic import Field

from taleboard.schema.base import Model

class JobKind(str, Enum):
    GENERATE = "generate"  # Draws layers (its tasks)
    IMPORT = "import"  # Breaks a story down into the project's registries, scenes and shots

class JobStatus(str, Enum):
    """
    Where a generation job is up to.
    """
    QUEUED = "queued"  # Waiting for the project's earlier jobs to finish
    RUNNING = "running"
    COMPLETE = "complete"  # Every task has been tried -- some may still have failed (see each task)
    FAILED = "failed"  # The job itself couldn't finish (eg:- every delivery attempt failed)

class TaskStatus(str, Enum):
    """
    How drawing one layer went.
    """
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"  # Eg:- its cutout came out empty or see-through, even after a second try
    SKIPPED = "skipped"  # The layer (or its shot) was deleted before its turn came

class GenerationTask(Model):
    """
    One layer for a job to draw.

    Attributes:
        scene_id: str - The scene the layer's shot is in.
        shot_id: str - The shot the layer is in.
        layer_id: str - The layer to draw.
        status: TaskStatus - How drawing it went. Defaults to PENDING.
        error: str - Why it failed, if it did. Defaults to None.
    """
    scene_id: str
    shot_id: str
    layer_id: str
    status: TaskStatus = TaskStatus.PENDING
    error: str | None = None

class GenerationJob(Model):
    """
    One Generate request: the layers it is to draw, in order.

    Attributes:
        id: str - Unique ID of the job. Defaults to a new random ID.
        created_at: datetime - When it was asked for (UTC).
        status: JobStatus - Where it's up to. Defaults to QUEUED.
        tasks: list[GenerationTask] - The layers to draw, in order. Defaults to [].
        error: str - Why the job itself failed, if it did. Defaults to None.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime
    kind: JobKind = JobKind.GENERATE
    draw: bool = False
    status: JobStatus = JobStatus.QUEUED
    tasks: list[GenerationTask] = Field(default_factory=list)
    error: str | None = None