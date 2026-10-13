"""
Runs render jobs from the queue -- breaks the story down once, then renders each shot, saving each one as soon as it's done.

Every delivery of a job does the same thing: render whatever isn't finished yet. So a retry, a duplicate delivery and a continuation all resume from the same place. The only record of rendering progress is each shot's generated_frame -- the same thing status polling reads.

    1. Claim the job (a lease stops two deliveries rendering at once)
    2. If the breakdown isn't saved yet (no shot_count), run it and save it as the checkpoint -- it is never re-run once saved, as a new breakdown would change the text the cache keys are built from
    3. Render each shot without a generated_frame through the persistent caches, saving each one as it finishes
    4. If time runs short, release the lease, enqueue the same job again, and stop -- the next delivery carries on from step 3

Attributes:
    MAX_ATTEMPTS: int - Deliveries before a failing job is marked failed. Must match the queue's maxReceiveCount.
    CONTINUATION_MARGIN_MS: int - Time (in milliseconds) that must remain to start rendering another shot -- any less, and the job is handed over.
    BUSY_RETRY_MARGIN_S: int - Extra seconds added after a lease expires before a busy delivery is retried, so it never arrives a moment too early.
    FAILED_RETRY_DELAY_S: int - Seconds before a transiently failed attempt is delivered again (the full visibility timeout would idle for 16 minutes).
    TOGETHER_KEY_PARAMETER_ENV: str - Environment variable naming the SSM parameter that holds the Together API key.
    BreakDown: Callable[[str],StoryBreakdown] - Story breakdown function (usually break_down_story, or mocked during testing).
    Render: Callable[...,RenderResult] - Shot rendering function (usually render_shot, or mocked during testing).
"""
import logging
import os
import boto3

from enum import Enum
from typing import Callable

from taleboard.jobs.queue import JobQueue, parse_message
from taleboard.parsing.story_breakdown import StoryBreakdown, break_down_story
from taleboard.rendering.shot_renderer import RenderResult, render_shot
from taleboard.schema.enums import ProjectStatus
from taleboard.storage.caches import PersistentBackgroundCache, PersistentPoseCache, PersistentReferenceCache
from taleboard.storage.project_store import ProjectStore

logging.getLogger("taleboard").setLevel(logging.INFO)  # Lambda only shows WARNING+ by default; this surfaces per-call timings

MAX_ATTEMPTS = 5
CONTINUATION_MARGIN_MS = 2 * 60 * 1000
BUSY_RETRY_MARGIN_S = 15
FAILED_RETRY_DELAY_S = 60
TOGETHER_KEY_PARAMETER_ENV = "TOGETHER_API_KEY_PARAMETER"

BreakDown = Callable[[str], StoryBreakdown]
Render = Callable[..., RenderResult]


class JobOutcome(str, Enum):
    """
    How one delivery of a render job ended.

    Attributes:
        COMPLETE: The job was completed successfully.
        CONTINUED: The job was handed over to a new delivery before time ran out.
        SKIPPED: The job was already finished, or superseded by another job.
    """
    COMPLETE = "complete"
    CONTINUED = "continued"
    SKIPPED = "skipped"


class JobBusyError(RuntimeError):
    """
    Raised when another delivery of the same job still holds its lease -- the message should be retried once the lease runs out, not dropped.

    Attributes:
        retry_after_s: int - Seconds until the holder's lease expires.
    """
    def __init__(self, message: str, retry_after_s: int):
        """
        Records how long until the job can be claimed.

        Arguments:
            message: str - Error message.
            retry_after_s: int - Seconds until the holder's lease expires.
        """
        super().__init__(message)
        self.retry_after_s = retry_after_s


def run_job(
    store: ProjectStore,
    queue: JobQueue,
    project_id: str,
    job_id: str,
    remaining_ms: Callable[[], int],
    break_down: BreakDown = break_down_story,
    render: Render = render_shot,
) -> JobOutcome:
    """
    Runs (or resumes) one render job.

    Raises a JobBusyError if another delivery of the same job is still running.

    Arguments:
        store: ProjectStore - Store the project is read from and written to.
        queue: JobQueue - Queue the job is handed back to if time runs short.
        project_id: str - Unique project ID.
        job_id: str - Unique render job ID.
        remaining_ms: Callable[[],int] - Returns the time left in this invocation, in milliseconds (usually the Lambda context's get_remaining_time_in_millis).
        break_down: BreakDown - Story breakdown function. Defaults to break_down_story.
        render: Render - Shot rendering function. Defaults to render_shot.

    Returns:
        JobOutcome - How this delivery ended.
    """
    if not store.claim_job(project_id, job_id):
        project = store.get_project(project_id)
        if project.job_id == job_id and project.status in (ProjectStatus.PENDING, ProjectStatus.IN_PROGRESS):
            raise JobBusyError(f"Job {job_id!r} is already being run by another delivery", store.lease_seconds_remaining(project_id))
        return JobOutcome.SKIPPED

    if store.get_project(project_id).shot_count is None:
        breakdown = break_down(store.load_story(project_id, job_id))
        store.save_breakdown(project_id, breakdown.characters, breakdown.shots)

    project = store.load_project(project_id)
    caches = {
        "character_cache": PersistentPoseCache(store, project_id),
        "background_cache": PersistentBackgroundCache(store, project_id),
        "reference_cache": PersistentReferenceCache(store, project_id),
    }
    for index, shot in enumerate(project.shots):
        if shot.generated_frame is not None:
            continue  # Rendered by an earlier delivery
        if remaining_ms() < CONTINUATION_MARGIN_MS:
            store.release_job(project_id, job_id)  # Released before re-queuing, so the continuation can always claim it
            queue.enqueue(project_id, job_id)
            return JobOutcome.CONTINUED
        result = render(shot, project.cast, **caches)
        store.save_rendered_shot(project_id, index, shot, result.image, result.needs_review)

    store.finish_job(project_id, job_id, ProjectStatus.COMPLETE)
    return JobOutcome.COMPLETE

def load_together_key() -> None:
    """
    Puts the Together AI API key into the environment (where the Together client looks for it), reading it from SSM Parameter Store.

    Runs once per Lambda container -- warm invocations find the key already set. Does nothing locally, where the key comes from .env instead.
    """
    parameter = os.environ.get(TOGETHER_KEY_PARAMETER_ENV)
    if parameter and "TOGETHER_API_KEY" not in os.environ:
        os.environ["TOGETHER_API_KEY"] = boto3.client("ssm").get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]


def handler(event: dict, context) -> None:
    """
    Worker Lambda entry point. The queue should deliver one message per invocation (batch size 1).

    Retryable failures are re-raised, so SQS delivers the message again. A delivery that finds the job busy is retried just after the holder's lease expires. After MAX_ATTEMPTS, or for a failure retrying can't fix, the job is marked failed instead.

    Arguments:
        event: dict - SQS event.
        context: LambdaContext - Lambda context, used for the time remaining.
    """
    load_together_key()
    store, queue = ProjectStore.from_env(), JobQueue.from_env()
    for record in event["Records"]:
        project_id, job_id = parse_message(record["body"])
        attempt = int(record["attributes"]["ApproximateReceiveCount"])
        try:
            run_job(store, queue, project_id, job_id, context.get_remaining_time_in_millis)
        except JobBusyError as e:
            # Comes back just after the holder's lease runs out -- rather than after the full visibility timeout -- usually bouncing only once
            queue.retry_after(record["receiptHandle"], e.retry_after_s + BUSY_RETRY_MARGIN_S)
            raise
        except Exception as e:
            logging.getLogger(__name__).exception("Render job %s failed (attempt %d of %d)", job_id, attempt, MAX_ATTEMPTS)
            if isinstance(e, ValueError) or attempt >= MAX_ATTEMPTS:  # ValueError means bad input (eg:- an empty story) -- retrying can't fix it
                store.finish_job(project_id, job_id, ProjectStatus.FAILED, error=str(e)[:500])
            else:
                store.release_job(project_id, job_id)
                # The lease is already released, so there's nothing to wait out -- retry soon rather than after the full visibility timeout
                queue.retry_after(record["receiptHandle"], FAILED_RETRY_DELAY_S)
                raise