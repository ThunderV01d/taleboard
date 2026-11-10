"""
Runs story import jobs from the generation queue: breaks the story down, writes it into the project, and (if asked) queues a generation job to draw every layer.

    1. Mark the job running (one that has already finished is left alone)
    2. Break the story down (every LLM call happens here, before anything is written)
    3. Clear the project of anything an earlier, failed delivery of this job wrote, then write the breakdown
    4. If the job says to draw everything, queue a generation job for every layer -- behind this one, as a project's jobs run in order
    5. Mark the job complete

An import is only ever run on an empty project (the import route checks), so clearing it in step 3 only removes what this job wrote before -- making a retry start cleanly rather than write everything twice.

A story that can't be broken down at all (eg:- it has no characters) fails the job at once, as a retry would fail the same way. Anything else -- Bedrock not answering, say -- fails the delivery, which is retried; after MAX_ATTEMPTS the job is marked failed.
"""
import logging
from datetime import datetime, timezone

from pydantic import ValidationError

from taleboard.generation.planning import Registry, layers_to_draw
from taleboard.jobs.generation_worker import FAILED_RETRY_DELAY_S, MAX_ATTEMPTS
from taleboard.jobs.queue import GenerationQueue, parse_message
from taleboard.parsing.bedrock_caller import MakeCaller, make_bedrock_caller
from taleboard.parsing.story_breakdown import break_down_story
from taleboard.parsing.story_import import write_breakdown
from taleboard.schema.generation import GenerationJob, GenerationTask, JobStatus
from taleboard.schema.storyboard import Character, Location, Prop
from taleboard.storage.storyboard_store import StoryboardStore

logger = logging.getLogger(__name__)


def run_import_job(
    boards: StoryboardStore,
    queue: GenerationQueue,
    project_id: str,
    job_id: str,
    make_caller: MakeCaller = make_bedrock_caller,
) -> GenerationJob | None:
    """
    Runs one story import job.

    Arguments:
        boards: StoryboardStore - Store the job and story are read from, and the project written to.
        queue: GenerationQueue - Queue the drawing job is put on.
        project_id: str - Unique project ID.
        job_id: str - Unique import job ID.
        make_caller: MakeCaller - LLM caller builder. Defaults to make_bedrock_caller.

    Returns:
        GenerationJob | None - The generation job queued to draw everything, if one was.
    """
    try:
        job = boards.get_job(project_id, job_id)
    except KeyError:
        return None  # Deleted, with its project
    if job.status in (JobStatus.COMPLETE, JobStatus.FAILED):
        return None
    boards.set_job_status(project_id, job_id, JobStatus.RUNNING)

    try:
        breakdown = break_down_story(boards.get_story(project_id, job_id), make_caller)
    except ValidationError:
        raise  # The model's answers never validated -- another delivery may do better
    except ValueError as error:
        # Nothing a retry would change -- eg:- a story with no characters
        boards.set_job_status(project_id, job_id, JobStatus.FAILED, error=str(error)[:500])
        return None

    _clear(boards, project_id)
    written = write_breakdown(boards, project_id, breakdown)

    drawing = None
    if job.draw:
        planned = layers_to_draw(written, Registry.load(boards, project_id))
        if planned:
            drawing = GenerationJob(
                created_at=datetime.now(timezone.utc),
                tasks=[GenerationTask(scene_id=p.scene.id, shot_id=p.shot.id, layer_id=p.layer.id) for p in planned],
            )
            boards.create_job(project_id, drawing)
            queue.enqueue(project_id, drawing.id)
    boards.set_job_status(project_id, job_id, JobStatus.COMPLETE)
    return drawing


def _clear(boards: StoryboardStore, project_id: str) -> None:
    """
    Removes every scene (with its shots) and registry entry from a project.
    """
    for scene in boards.list_scenes(project_id):
        boards.delete_scene(project_id, scene.id)
    for model in (Character, Prop, Location):
        for entry in boards.list_entries(project_id, model):
            boards.delete_entry(project_id, model, entry.id)


def handle_record(record: dict, make_caller: MakeCaller = make_bedrock_caller) -> None:
    """
    Handles one import job message, as the worker Lambda receives it.

    A failed delivery is retried a minute later, by re-raising (SQS delivers the message again); after MAX_ATTEMPTS the job is marked failed instead.

    Arguments:
        record: dict - One SQS record from the generation queue.
        make_caller: MakeCaller - LLM caller builder. Defaults to make_bedrock_caller.
    """
    boards, queue = StoryboardStore.from_env(), GenerationQueue.from_env()
    project_id, job_id = parse_message(record["body"])
    attempt = int(record["attributes"]["ApproximateReceiveCount"])
    try:
        run_import_job(boards, queue, project_id, job_id, make_caller)
    except Exception as e:
        logger.exception("Import job %s failed (attempt %d of %d)", job_id, attempt, MAX_ATTEMPTS)
        if attempt >= MAX_ATTEMPTS:
            try:
                boards.set_job_status(project_id, job_id, JobStatus.FAILED, error=str(e)[:500])
            except KeyError:
                pass  # Deleted meanwhile
            return
        queue.retry_after(record["receiptHandle"], FAILED_RETRY_DELAY_S)
        raise
