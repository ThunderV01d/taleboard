"""
Puts a project's jobs -- generation and story import -- on the SQS FIFO queue that the worker Lambda consumes. A message carries only the job's kind and IDs -- the job, its tasks and its story are in DynamoDB -- so it stays far below SQS's 256 KB limit, and a redelivered message rereads the job as it is now.
"""
import json
import os
import uuid

import boto3

from taleboard.schema.generation import JobKind
from taleboard.storage.storyboard_store import DEFAULT_REGION


class GenerationQueue:
    """
    Sends generation job messages to the SQS FIFO queue the worker consumes.

    Each message is in its project's message group, so a project's jobs are delivered one at a time and in the order they were asked for -- an image one job draws is always there for the next -- while different projects' jobs run side by side.

    Attributes:
        _sqs: SQS.Client - SQS client.
        _queue_url: str - URL of the generation job queue.
    """
    def __init__(self, queue_url: str, region_name: str = DEFAULT_REGION):
        """
        Connects to the queue. Nothing is created -- the queue must already exist.

        Arguments:
            queue_url: str - URL of the generation job queue (a FIFO queue).
            region_name: str - AWS Region of the queue. Defaults to DEFAULT_REGION.
        """
        self._sqs = boto3.client("sqs", region_name=region_name)
        self._queue_url = queue_url

    @classmethod
    def from_env(cls) -> "GenerationQueue":
        """
        Connects using the TALEBOARD_GENERATION_QUEUE_URL and (optionally) AWS_REGION environment variables.

        Returns:
            GenerationQueue - A connected GenerationQueue.
        """
        return cls(os.environ["TALEBOARD_GENERATION_QUEUE_URL"], os.environ.get("AWS_REGION", DEFAULT_REGION))

    def enqueue(self, project_id: str, job_id: str, kind: JobKind = JobKind.GENERATE) -> None:
        """
        Queues a job (or the continuation of one) behind the project's other jobs.

        Every send gets its own deduplication ID: a continuation's message is the same as the job's first, and FIFO queues drop a repeat of the same ID.

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique job ID.
            kind: JobKind - What the job does (which the worker runs it as). Defaults to GENERATE.
        """
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"kind": kind.value, "project_id": project_id, "job_id": job_id}),
            MessageGroupId=project_id,
            MessageDeduplicationId=uuid.uuid4().hex,
        )

    def retry_after(self, receipt_handle: str, delay_s: int) -> None:
        """
        Makes a received message visible again after a delay, rather than after the queue's full visibility timeout. The project's later jobs wait meanwhile, as a FIFO group always does.

        Arguments:
            receipt_handle: str - The received message's receipt handle.
            delay_s: int - Seconds until the message is delivered again (at most 12 hours, SQS's limit).
        """
        self._sqs.change_message_visibility(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=min(delay_s, 12*60*60))


def parse_message(body: str) -> tuple[str, str]:
    """
    Reads the IDs out of a generation job message.

    Arguments:
        body: str - Message body, as sent by GenerationQueue.enqueue.

    Returns:
        tuple[str,str] - Project ID and job ID.
    """
    data = json.loads(body)
    return data["project_id"], data["job_id"]


def message_kind(body: str) -> JobKind:
    """
    Reads what kind of job a message is for.

    Arguments:
        body: str - Message body, as sent by GenerationQueue.enqueue.

    Returns:
        JobKind - The job's kind.
    """
    return JobKind(json.loads(body).get("kind", JobKind.GENERATE.value))