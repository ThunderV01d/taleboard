"""
Runs generation jobs from the generation queue: draws each of a job's layers in order, saving each image into its shot as soon as it's done.

Every delivery of a job does the same thing -- draw whatever task is still pending -- so a retry and a continuation both carry on from the same place. A task's status is the only record of progress, and is what the editor follows.

The queue is FIFO, grouped by project: a project's jobs are delivered one at a time, so no two of them ever draw at once, and no lease is needed.

    1. Mark the job running (one that has already finished is left alone)
    2. Draw each pending task's layer, save it into its shot, and record how it went
    3. If time runs short, queue the same job again and stop -- the next delivery carries on from step 2
    4. Mark the job complete (some tasks may have failed -- each says why)

A layer that can't be drawn (its cutout came out empty twice, Together AI refused its prompt, or what it shows is gone from the registry) fails alone, and the job goes on. Anything else -- Together AI not answering, say -- fails the delivery, which is retried; after MAX_ATTEMPTS the job is marked failed.

Attributes:
    MAX_ATTEMPTS: int - Deliveries before a failing job is marked failed. Must match the generation queue's maxReceiveCount.
    CONTINUATION_MARGIN_MS: int - Time (in milliseconds) that must remain to start drawing another layer -- any less, and the job is handed over.
    FAILED_RETRY_DELAY_S: int - Seconds before a failed delivery is tried again (rather than the queue's full visibility timeout).
    REFUSED_ERROR: str - Error recorded on a layer whose prompt the image model refused.
    REJECTED_ERROR: str - Error recorded on a layer whose prompt the image model rejects (not a content refusal, just a bad request).
    MakeGenerator: Callable[[str,StoryboardStore],Generator] - Builds the generator for a project (usually Generator, or a fake in tests).
"""
import logging
from enum import Enum
from typing import Callable

from taleboard.generation.engine import Generator
from taleboard.jobs.queue import GenerationQueue, parse_message
from taleboard.generation.cutouts import CutoutRejectedError
from taleboard.generation.together_caller import ContentRefusedError, RequestRejectedError
from taleboard.schema.generation import JobStatus, TaskStatus
from taleboard.schema.layers import GeneratedLayer
from taleboard.schema.storyboard import Character, Location, Prop
from taleboard.storage.storyboard_store import StoryboardStore

MAX_ATTEMPTS = 5
CONTINUATION_MARGIN_MS = 6 * 60 * 1000
FAILED_RETRY_DELAY_S = 60

REFUSED_ERROR = (
    "The image model refused to draw this under its safety policy -- change what the character, prop or place is "
    "described as (or the layer's action), then generate it again"
)

REJECTED_ERROR = "The image model couldn't draw this just now -- generate it again in a while"

MakeGenerator = Callable[[str, StoryboardStore], Generator]


class GenerationOutcome(str, Enum):
    """
    How one delivery of a generation job ended.
    """
    COMPLETE = "complete"  # Every task has been tried
    CONTINUED = "continued"  # Time ran short; the job was queued again to carry on
    SKIPPED = "skipped"  # The job had already finished, or no longer exists


def run_generation_job(
    boards: StoryboardStore,
    queue: GenerationQueue,
    project_id: str,
    job_id: str,
    remaining_ms: Callable[[], int],
    make_generator: MakeGenerator = Generator,
) -> GenerationOutcome:
    """
    Runs (or carries on with) one generation job.

    Arguments:
        boards: StoryboardStore - Store the job, shots and registries are read from and written to.
        queue: GenerationQueue - Queue the job is handed back to if time runs short.
        project_id: str - Unique project ID.
        job_id: str - Unique generation job ID.
        remaining_ms: Callable[[],int] - Returns the time left in this invocation, in milliseconds (usually the Lambda context's get_remaining_time_in_millis).
        make_generator: MakeGenerator - Builds the project's generator. Defaults to Generator.

    Returns:
        GenerationOutcome - How this delivery ended.
    """
    try:
        job = boards.get_job(project_id, job_id)
    except KeyError:
        return GenerationOutcome.SKIPPED  # Deleted, with its project
    if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
        return GenerationOutcome.SKIPPED
    boards.set_job_status(project_id, job_id, JobStatus.RUNNING)

    # Loaded once for the whole job -- the generator records new plates and references on these same entries as it goes
    locations = {entry.id: entry for entry in boards.list_entries(project_id, Location)}
    characters = {entry.id: entry for entry in boards.list_entries(project_id, Character)}
    props = {entry.id: entry for entry in boards.list_entries(project_id, Prop)}
    generator = make_generator(project_id, boards)

    for index, task in enumerate(job.tasks):
        if task.status != TaskStatus.PENDING:
            continue  # Done by an earlier delivery
        if remaining_ms() < CONTINUATION_MARGIN_MS:
            queue.enqueue(project_id, job_id)
            return GenerationOutcome.CONTINUED
        status, error = _draw(boards, generator, project_id, task, locations, characters, props)
        boards.set_task_status(project_id, job_id, index, status, error)

    boards.set_job_status(project_id, job_id, JobStatus.COMPLETE)
    return GenerationOutcome.COMPLETE


def _draw(boards, generator, project_id, task, locations, characters, props) -> tuple[TaskStatus, str | None]:
    """
    Draws one task's layer and saves it into its shot -- or says why it couldn't. Errors that a retry might fix are raised.
    """
    try:
        scene = boards.get_scene(project_id, task.scene_id)
        shot = boards.get_shot(project_id, task.scene_id, task.shot_id)
    except KeyError:
        return TaskStatus.SKIPPED, None  # The scene or shot was deleted
    layer = next((l for l in shot.all_layers() if l.id == task.layer_id), None)
    if not isinstance(layer, GeneratedLayer):
        return TaskStatus.SKIPPED, None  # The layer was deleted (or its ID now belongs to a text or image layer)

    location = locations.get(scene.location_id)
    if location is None:
        return TaskStatus.FAILED, f"The scene's location {scene.location_id!r} is no longer in the project"
    try:
        drawn = generator.generate_layer(layer, shot, scene, location, characters, props)
    except CutoutRejectedError as error:
        return TaskStatus.FAILED, str(error)[:300]
    except ContentRefusedError:
        # Never retried: the same text is refused every time, and retrying would hold up the project's other jobs
        return TaskStatus.FAILED, REFUSED_ERROR
    except RequestRejectedError as error:
        # Already retried for about a minute -- this layer waits for the user, rather than blocking every layer after it
        logging.getLogger(__name__).warning("Layer %s rejected: %s", task.layer_id, error)
        return TaskStatus.FAILED, f"{REJECTED_ERROR}({str(error.__cause__ or error)[:200]})"
    except KeyError as error:
        return TaskStatus.FAILED, f"{error.args[0] if error.args else 'Something it shows'} is no longer in the project"

    if not boards.save_generated_layer(project_id, task.scene_id, task.shot_id, drawn):
        return TaskStatus.SKIPPED, None  # Deleted while it was being drawn
    return TaskStatus.DONE, None


def handle_record(record: dict, remaining_ms: Callable[[], int], make_generator: MakeGenerator = Generator) -> None:
    """
    Handles one generation queue message, as the worker Lambda receives it.

    A failed delivery is retried a minute later, by re-raising (SQS delivers the message again); after MAX_ATTEMPTS the job is marked failed instead, keeping whatever tasks it finished.

    Arguments:
        record: dict - One SQS record from the generation queue.
        remaining_ms: Callable[[],int] - Returns the time left in this invocation, in milliseconds.
        make_generator: MakeGenerator - Builds the project's generator. Defaults to Generator.
    """
    boards, queue = StoryboardStore.from_env(), GenerationQueue.from_env()
    project_id, job_id = parse_message(record["body"])
    attempt = int(record["attributes"]["ApproximateReceiveCount"])
    try:
        run_generation_job(boards, queue, project_id, job_id, remaining_ms, make_generator)
    except Exception as e:
        logging.getLogger(__name__).exception("Generation job %s failed (attempt %d of %d)", job_id, attempt, MAX_ATTEMPTS)
        if attempt >= MAX_ATTEMPTS:
            try:
                boards.set_job_status(project_id, job_id, JobStatus.FAILED, error=str(e)[:500])
            except KeyError:
                pass  # Deleted meanwhile
            return
        queue.retry_after(record["receiptHandle"], FAILED_RETRY_DELAY_S)
        raise