"""
Recovers jobs (generation and story import alike) whose messages ended up in the dead-letter queue.

A message is dead-lettered when every delivery attempt failed without the worker marking the job failed itself -- eg:- the worker ran out of memory or time before its own error handling ran, or busy bounces used up the attempts. Without this, such a job would stay "in progress" forever, and the user could never resubmit.

Only ever writes a generation job's own item. IAM can't express that boundary within the single table, so this code is what enforces it.

Attributes:
    DEAD_LETTER_ERROR: str - Error recorded on a recovered job. SQS doesn't say why the deliveries failed, so the worker's logs hold the details.
"""
import logging

from taleboard.jobs.queue import parse_message
from taleboard.schema.generation import JobStatus
from taleboard.storage.storyboard_store import StoryboardStore

DEAD_LETTER_ERROR = "dead-lettered: every delivery attempt failed (see the worker's logs)"


def handler(event: dict, context) -> None:
    """
    DLQ recovery Lambda entry point -- marks each dead-lettered job failed, unless it has already finished.

    Arguments:
        event: dict - SQS event from the dead-letter queue.
        context: LambdaContext - Lambda context (unused).
    """
    boards = StoryboardStore.from_env()
    for record in event["Records"]:
        project_id, job_id = parse_message(record["body"])
        _fail_generation_job(StoryboardStore.from_env(), project_id, job_id)


def _fail_generation_job(boards: StoryboardStore, project_id: str, job_id: str) -> None:
    """
    Marks a dead-lettered generation job failed, unless it has already finished (or no longer exists). Its finished tasks keep their results.

    Arguments:
        boards: StoryboardStore - Store the job is in.
        project_id: str - Unique project ID.
        job_id: str - Unique generation job ID.
    """
    try:
        if boards.get_job(project_id, job_id).status in (JobStatus.COMPLETE, JobStatus.FAILED):
            return
        boards.set_job_status(project_id, job_id, JobStatus.FAILED, error=DEAD_LETTER_ERROR)
    except KeyError:
        return  # Deleted, with its project
    logging.getLogger(__name__).warning("Marked dead-lettered generation job %s (project %s) as failed", job_id, project_id)