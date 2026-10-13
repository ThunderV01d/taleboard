"""
Recovers render jobs whose messages ended up in the dead-letter queue.

A message is dead-lettered when every delivery attempt failed without the worker marking the job failed itself -- eg:- the worker ran out of memory or time before its own error handling ran, or busy bounces used up the attempts. Without this, such a job would stay "in progress" forever, and the user could never resubmit.

Only ever writes the project's METADATA item. IAM can't express that boundary within the single table, so this code is what enforces it.

Attributes:
    DEAD_LETTER_ERROR: str - Error recorded on a recovered job. SQS doesn't say why the deliveries failed, so the worker's logs hold the details.
"""
import logging

from taleboard.jobs.queue import parse_message
from taleboard.storage.project_store import ProjectStore

DEAD_LETTER_ERROR = "dead-lettered: every delivery attempt failed (see the worker's logs)"


def handler(event: dict, context) -> None:
    """
    DLQ recovery Lambda entry point -- marks each dead-lettered job failed, unless it has already finished.

    Arguments:
        event: dict - SQS event from the dead-letter queue.
        context: LambdaContext - Lambda context (unused).
    """
    store = ProjectStore.from_env()
    for record in event["Records"]:
        project_id, job_id = parse_message(record["body"])
        if store.fail_unfinished_job(project_id, job_id, DEAD_LETTER_ERROR):
            logging.getLogger(__name__).warning("Marked dead-lettered job %s (project %s) as failed", job_id, project_id)