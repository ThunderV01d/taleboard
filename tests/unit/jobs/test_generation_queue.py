"""
Unit tests for the generation job queue, against moto's fake of an SQS FIFO queue (see tests/unit/conftest.py).

Covers what a message carries, and that each project's jobs share a message group -- which is what makes them run one at a time, in order.
"""
import json

import boto3
import pytest

from taleboard.jobs.queue import GenerationQueue, message_kind
from taleboard.schema.generation import JobKind

REGION = "eu-west-2"


@pytest.fixture
def fifo(aws, monkeypatch):
    """
    A fake FIFO queue, with TALEBOARD_GENERATION_QUEUE_URL pointing at it.

    Arguments:
        aws: None - The shared fakes (so this runs inside moto).
        monkeypatch: pytest.MonkeyPatch - Sets the environment variable.

    Returns:
        str - The queue's URL.
    """
    url = boto3.client("sqs", region_name=REGION).create_queue(QueueName="generation-test.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
    monkeypatch.setenv("TALEBOARD_GENERATION_QUEUE_URL", url)
    return url


def _receive(url: str) -> list[dict]:
    """
    Every message waiting on the queue, with its attributes.
    """
    sqs = boto3.client("sqs", region_name=REGION)
    messages = []
    while batch := sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10, AttributeNames=["All"]).get("Messages"):
        for message in batch:
            messages.append(message)
            sqs.delete_message(QueueUrl=url, ReceiptHandle=message["ReceiptHandle"])
    return messages


def test_a_job_is_sent_in_its_projects_message_group(fifo):
    """
    Verifies that a message names the job, says it's a generation job, and is grouped by project.
    """
    GenerationQueue.from_env().enqueue("p1", "j1")

    [message] = _receive(fifo)
    assert json.loads(message["Body"]) == {"kind": "generate", "project_id": "p1", "job_id": "j1"}
    assert message["Attributes"]["MessageGroupId"] == "p1"


def test_sending_the_same_job_again_is_never_dropped_as_a_duplicate(fifo):
    """
    Verifies that a continuation (the same job, sent again) gets through -- a FIFO queue drops repeats of a deduplication ID.
    """
    queue = GenerationQueue.from_env()
    queue.enqueue("p1", "j1")
    queue.enqueue("p1", "j1")

    assert len(_receive(fifo)) == 2


def test_an_import_job_says_so_and_shares_its_projects_group(fifo):
    """
    Verifies that an import job's message names its kind, and is in the same group as the project's generation jobs -- so the drawing it queues runs after it.
    """
    queue = GenerationQueue.from_env()
    queue.enqueue("p1", "import-1", JobKind.IMPORT)
    queue.enqueue("p1", "draw-1")

    first, second = _receive(fifo)
    assert [message_kind(m["Body"]) for m in (first, second)] == [JobKind.IMPORT, JobKind.GENERATE]
    assert first["Attributes"]["MessageGroupId"] == second["Attributes"]["MessageGroupId"] == "p1"
    assert message_kind(json.dumps({"project_id": "p1", "job_id": "old"})) == JobKind.GENERATE  # A message from before kinds were sent
