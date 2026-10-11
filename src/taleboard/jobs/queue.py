"""
Puts render jobs on the SQS queue that the worker Lambda consumes.

A message carries only IDs -- the story itself is in S3 -- so it stays far below SQS's 256 KB limit, and a redelivered message rereads exactly the story that was submitted.
"""
import json
import os

import boto3

from taleboard.storage.project_store import DEFAULT_REGION


class JobQueue:
    """
    Sends render job messages to SQS.

    Attributes:
        _sqs: SQS.Client - SQS client.
        _queue_url: str - URL of the render job queue.
    """
    def __init__(self, queue_url: str, region_name: str = DEFAULT_REGION):
        """
        Connects to the queue. Nothing is created -- the queue must already exist.

        Arguments:
            queue_url: str - URL of the render job queue.
            region_name: str - AWS Region of the queue. Defaults to DEFAULT_REGION.
        """
        self._sqs = boto3.client("sqs", region_name=region_name)
        self._queue_url = queue_url

    @classmethod
    def from_env(cls) -> "JobQueue":
        """
        Connects using the TALEBOARD_QUEUE_URL and (optionally) AWS_REGION environment variables.

        Returns:
            JobQueue - A connected JobQueue.
        """
        return cls(os.environ["TALEBOARD_QUEUE_URL"], os.environ.get("AWS_REGION", DEFAULT_REGION))

    def enqueue(self, project_id: str, job_id: str) -> None:
        """
        Queues a render job (or the continuation of one).

        Arguments:
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
        """
        self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=json.dumps({"project_id": project_id, "job_id": job_id}))

    def retry_after(self, receipt_handle: str, delay_s: int) -> None:
        """
        Makes a received message visible again after a delay, rather than after the queue's full visibility timeout.

        Arguments:
            receipt_handle: str - The received message's receipt handle.
            delay_s: int - Seconds until the message is delivered again (at most 12 hours, SQS's limit).
        """
        self._sqs.change_message_visibility(QueueUrl=self._queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=min(delay_s, 12 * 60 * 60))


def parse_message(body: str) -> tuple[str, str]:
    """
    Reads the IDs out of a render job message.

    Arguments:
        body: str - Message body, as sent by JobQueue.enqueue.

    Returns:
        tuple[str,str] - Project ID and job ID.
    """
    data = json.loads(body)
    return data["project_id"], data["job_id"]