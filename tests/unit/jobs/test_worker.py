"""
Unit tests for the render job worker.

Runs against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py), with a fake story breakdown and fake image generation -- so no AWS, Bedrock or Together AI calls are made.
"""
import io
import json
import os
import boto3
from moto import mock_aws
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from PIL import Image

from taleboard.jobs import worker
from taleboard.jobs.worker import JobBusyError, JobOutcome, run_job
from taleboard.jobs.queue import JobQueue
from taleboard.storage.project_store import JOB_LEASE_SECONDS
from taleboard.parsing.llm_schemas import LLMCastOutput
from taleboard.parsing.story_breakdown import StoryBreakdown
from taleboard.rendering.shot_renderer import render_shot
from taleboard.schema.enums import CameraAngle, Orientation, PositionCell, ProjectStatus, ShotSize, SizeInFrame
from taleboard.schema.models import Character, Location, Region, Shot


def _png() -> bytes:
    """
    Builds a small, fully opaque image -- a successful generation and cutout.

    Returns:
        bytes - Image file (PNG, in bytes).
    """
    buffer = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(index: int, alice_action: str | None) -> Shot:
    """
    Builds a shot at the lighthouse with its own details, optionally with Alice in it.

    Arguments:
        index: int - Used in the description and details, and as the paragraph index.
        alice_action: str - Alice's action in the shot, or None to leave her out.

    Returns:
        Shot - A Shot object.
    """
    regions = [Region(character_id="alice", position=PositionCell.MID_CENTER, size=SizeInFrame.MEDIUM, orientation=Orientation.LEFT, action=alice_action)] if alice_action else []
    return Shot(description=f"shot {index}", location_id="lighthouse", details=f"details {index}", regions=regions, paragraph_index=index,
                shot_size=ShotSize.MEDIUM, angle=CameraAngle.EYE_LEVEL, duration_s=2.0)


def _fakes(crash_on_shot: int | None = None):
    """
    Builds a fake story breakdown and a fake renderer, both counting their calls.

    The breakdown always returns 3 shots: Alice in shots 0 and 2, and none in shot 1. Every shot has its own details, so uninterrupted, the job makes 8 generation calls -- shot 0: master plate + medium background + its details + reference + pose; shot 1: its details; shot 2: its details + pose.

    Arguments:
        crash_on_shot: int - Paragraph index of a shot whose first render attempt raises, simulating a worker crash. Defaults to None (no crash).

    Returns:
        tuple[BreakDown,Render,dict[str,int]] - Fake breakdown, fake renderer, and the call counters ("break_down", "generate").
    """
    calls = {"break_down": 0, "generate": 0}
    crash = {"pending": crash_on_shot is not None}

    def fake_break_down(story_text: str) -> StoryBreakdown:
        """
        Counts the call and returns a fixed 3-shot breakdown.

        Arguments:
            story_text: str - The story (ignored).

        Returns:
            StoryBreakdown - Fixed breakdown with Alice in shots 0 and 2.
        """
        calls["break_down"] += 1
        return StoryBreakdown(cast={}, characters={"alice": Character(name="Alice", description="A woman.")},
                              shots=[_shot(0, "standing"), _shot(1, None), _shot(2, "waving")],
                              locations={"lighthouse": Location(name="Lighthouse", description="a round stone lamp room")})

    def fake_generate(text: str, negative_text: str, reference_images: list[bytes] | None = None) -> bytes:
        """
        Counts the call and returns an opaque image.

        Arguments:
            text: str - Prompt (ignored).
            negative_text: str - Negative prompt (ignored).
            reference_images: list[bytes] - Reference images (ignored). Defaults to None.

        Returns:
            bytes - Image file (in bytes).
        """
        calls["generate"] += 1
        return _png()

    def fake_render(shot: Shot, characters: dict[str, Character], **caches):
        """
        Renders through the real render_shot (and so the real persistent caches), with fake generation -- crashing once first if asked to.

        Arguments:
            shot: Shot - Shot to render.
            characters: dict[str,Character] - The cast.
            caches: dict - The persistent caches, as passed by run_job.

        Returns:
            RenderResult - The render result.
        """
        if crash["pending"] and shot.paragraph_index == crash_on_shot:
            crash["pending"] = False
            raise RuntimeError("worker crashed")
        return render_shot(shot, characters, generate_image=fake_generate, remove_background=lambda raw: _png(), **caches)

    return fake_break_down, fake_render, calls


def _submit(store) -> str:
    """
    Creates a project and submits a story to it as job "job-1".

    Arguments:
        store: ProjectStore - Store to create the project in.

    Returns:
        str - The project's ID.
    """
    project = store.create_project("Lighthouse")
    store.submit_story(project.project_id, "job-1", "Alice waved.")
    return project.project_id


def _plenty_of_time() -> int:
    """
    Stands in for a Lambda invocation with lots of time left.

    Returns:
        int - A very large number of milliseconds.
    """
    return 10**9


def test_a_job_renders_every_shot_and_completes(store, queue):
    """
    Verifies that a job breaks the story down, renders and saves every shot, and marks the project complete.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _submit(store)
    break_down, render, calls = _fakes()

    assert run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render) == JobOutcome.COMPLETE

    project = store.load_project(pid)
    assert project.status == ProjectStatus.COMPLETE
    assert project.shot_count == 3
    assert all(shot.generated_frame for shot in project.shots)
    assert calls == {"break_down": 1, "generate": 8}


def test_a_crashed_job_resumes_without_repaying_or_re_breaking_down(store, queue):
    """
    Verifies job-level idempotency: a worker that crashes partway through, then is redelivered, finishes the job with exactly the calls an uninterrupted run would make.

    The breakdown isn't re-run, already-rendered shots aren't touched, and the interrupted shot reuses the cached reference image.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _submit(store)
    break_down, render, calls = _fakes(crash_on_shot=2)

    with pytest.raises(RuntimeError, match="worker crashed"):
        run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render)
    assert [s.generated_frame is not None for s in store.list_shots(pid)] == [True, True, False]

    store.release_job(pid, "job-1")  # What the handler does on a retryable failure (or what lease expiry does after a hard crash)
    assert run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render) == JobOutcome.COMPLETE

    assert calls == {"break_down": 1, "generate": 8}
    assert [s.paragraph_index for s in store.list_shots(pid)] == [0, 1, 2]


def test_a_job_running_out_of_time_hands_itself_over(store, queue):
    """
    Verifies continuation: with time running short, the job saves what it has, re-queues itself, and the next delivery finishes it.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _submit(store)
    break_down, render, calls = _fakes()
    time_left = iter([10**9])  # Enough time for the first shot, then none

    outcome = run_job(store, queue, pid, "job-1", lambda: next(time_left, 0), break_down, render)

    assert outcome == JobOutcome.CONTINUED
    messages = queue._sqs.receive_message(QueueUrl=queue._queue_url)["Messages"]
    assert json.loads(messages[0]["Body"]) == {"project_id": pid, "job_id": "job-1"}
    assert run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render) == JobOutcome.COMPLETE
    assert calls == {"break_down": 1, "generate": 8}


def test_a_duplicate_delivery_of_a_running_job_is_retried_later(store, queue):
    """
    Verifies that a second delivery of a job another worker holds is sent back to the queue, not dropped.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _submit(store)
    store.claim_job(pid, "job-1")  # Another worker holds the job
    break_down, render, calls = _fakes()

    with pytest.raises(JobBusyError) as busy:
        run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render)
    assert JOB_LEASE_SECONDS - 5 <= busy.value.retry_after_s <= JOB_LEASE_SECONDS
    assert calls == {"break_down": 0, "generate": 0}


def test_redelivering_a_finished_job_does_nothing(store, queue):
    """
    Verifies that a redelivered message for a completed job is skipped without any work.

    Arguments:
        store: ProjectStore - Fake-backed store.
        queue: JobQueue - Fake-backed queue.
    """
    pid = _submit(store)
    break_down, render, calls = _fakes()
    run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render)

    assert run_job(store, queue, pid, "job-1", _plenty_of_time, break_down, render) == JobOutcome.SKIPPED
    assert calls == {"break_down": 1, "generate": 8}


def _sqs_event(project_id: str, attempt: int) -> dict:
    """
    Builds an SQS event as Lambda delivers it.

    Arguments:
        project_id: str - Unique project ID.
        attempt: int - Delivery attempt number (SQS's ApproximateReceiveCount).

    Returns:
        dict - SQS event holding one message for job "job-1".
    """
    return {"Records": [{"body": json.dumps({"project_id": project_id, "job_id": "job-1"}), "receiptHandle": "receipt-1", "attributes": {"ApproximateReceiveCount": str(attempt)}}]}


_CONTEXT = SimpleNamespace(get_remaining_time_in_millis=_plenty_of_time)


def _failing_run_job(error: Exception):
    """
    Builds a stand-in for run_job that claims the job, then fails.

    Arguments:
        error: Exception - Error to raise.

    Returns:
        Callable - The stand-in.
    """
    def failing(store, queue, project_id, job_id, remaining_ms):
        """
        Claims the job, then raises.

        Arguments:
            store: ProjectStore - Store holding the job.
            queue: JobQueue - Queue (ignored).
            project_id: str - Unique project ID.
            job_id: str - Unique render job ID.
            remaining_ms: Callable[[],int] - Time remaining (ignored).
        """
        store.claim_job(project_id, job_id)
        raise error
    return failing


def test_handler_fails_a_job_straight_away_on_bad_input(store, monkeypatch):
    """
    Verifies that a ValueError (eg:- an empty story) marks the job failed on the first attempt, without a retry.

    Arguments:
        store: ProjectStore - Fake-backed store.
        monkeypatch: pytest.MonkeyPatch - Used to swap in a failing run_job.
    """
    pid = _submit(store)
    monkeypatch.setattr(worker, "run_job", _failing_run_job(ValueError("Story is empty")))

    worker.handler(_sqs_event(pid, attempt=1), _CONTEXT)

    project = store.get_project(pid)
    assert project.status == ProjectStatus.FAILED
    assert project.error == "Story is empty"


def test_handler_retries_a_transient_failure_and_frees_the_job(store, monkeypatch):
    """
    Verifies that a transient failure is re-raised (so SQS redelivers it) with the lease released, and the message set to come back after FAILED_RETRY_DELAY_S rather than the full visibility timeout.

    Arguments:
        store: ProjectStore - Fake-backed store.
        monkeypatch: pytest.MonkeyPatch - Used to swap in a failing run_job.
    """
    pid = _submit(store)
    monkeypatch.setattr(worker, "run_job", _failing_run_job(RuntimeError("Bedrock timed out")))
    retries = []
    monkeypatch.setattr(JobQueue, "retry_after", lambda self,receipt_handle,delay_s: retries.append((receipt_handle, delay_s)))
    with pytest.raises(RuntimeError):
        worker.handler(_sqs_event(pid, attempt=1), _CONTEXT)

    assert store.get_project(pid).status == ProjectStatus.IN_PROGRESS
    assert store.claim_job(pid, "job-1") is True
    assert retries == [("receipt-1", worker.FAILED_RETRY_DELAY_S)]


def test_handler_fails_a_job_after_the_last_attempt(store, monkeypatch):
    """
    Verifies that a transient failure on the final attempt marks the job failed, rather than leaving it in progress forever.

    Arguments:
        store: ProjectStore - Fake-backed store.
        monkeypatch: pytest.MonkeyPatch - Used to swap in a failing run_job.
    """
    pid = _submit(store)
    monkeypatch.setattr(worker, "run_job", _failing_run_job(RuntimeError("Bedrock timed out")))

    worker.handler(_sqs_event(pid, attempt=worker.MAX_ATTEMPTS), _CONTEXT)

    assert store.get_project(pid).status == ProjectStatus.FAILED

def test_handler_retries_a_busy_delivery_just_after_the_lease_expires(store, monkeypatch):
    """
    Verifies that a busy delivery is re-raised with its message set to reappear just after the holder's lease runs out -- not after the full visibility timeout.

    Arguments:
        store: ProjectStore - Fake-backed store.
        monkeypatch: pytest.MonkeyPatch - Used to record the retry delay.
    """
    pid = _submit(store)
    store.claim_job(pid, "job-1")  # Another worker holds the job
    retries = []
    monkeypatch.setattr(JobQueue, "retry_after", lambda self, receipt_handle, delay_s: retries.append((receipt_handle, delay_s)))

    with pytest.raises(JobBusyError):
        worker.handler(_sqs_event(pid, attempt=1), _CONTEXT)

    [(receipt_handle, delay_s)] = retries
    assert receipt_handle == "receipt-1"
    assert JOB_LEASE_SECONDS <= delay_s <= JOB_LEASE_SECONDS + worker.BUSY_RETRY_MARGIN_S

def test_the_together_key_is_loaded_from_parameter_store(aws, monkeypatch):
    """
    Verifies that the worker reads the Together AI key from SSM Parameter Store when one is configured.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes (provides fake credentials and an active moto mock).
        monkeypatch: pytest.MonkeyPatch - Used to set and clear environment variables.
    """
    boto3.client("ssm").put_parameter(Name="/taleboard/together-api-key", Value="secret-key", Type="SecureString")
    monkeypatch.setenv(worker.TOGETHER_KEY_PARAMETER_ENV, "/taleboard/together-api-key")
    monkeypatch.delenv("TOGETHER_API_KEY", raising=False)

    worker.load_together_key()

    assert os.environ["TOGETHER_API_KEY"] == "secret-key"


def test_an_existing_together_key_is_left_alone(monkeypatch):
    """
    Verifies that a key already in the environment (eg:- from .env locally) is used as-is, without calling SSM.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to set environment variables.
    """
    monkeypatch.setenv(worker.TOGETHER_KEY_PARAMETER_ENV, "/taleboard/together-api-key")
    monkeypatch.setenv("TOGETHER_API_KEY", "from-dotenv")

    worker.load_together_key()  # Would fail without credentials if it tried to call SSM

    assert os.environ["TOGETHER_API_KEY"] == "from-dotenv"

def test_handler_retries_an_llm_response_that_failed_validation(store, monkeypatch):
    """
    Verifies that a pydantic ValidationError (an LLM response that failed validation) gets the normal retries, even though pydantic makes it a ValueError -- only real bad input fails a job straight away.

    Arguments:
        store: ProjectStore - Fake-backed store.
        monkeypatch: pytest.MonkeyPatch - Used to swap in a failing run_job and record the retry.
    """
    try:
        LLMCastOutput.model_validate({})
    except ValidationError as e:
        validation_error = e
    pid = _submit(store)
    monkeypatch.setattr(worker, "run_job", _failing_run_job(validation_error))
    monkeypatch.setattr(JobQueue, "retry_after", lambda self, receipt_handle, delay_s: None)

    with pytest.raises(ValidationError):
        worker.handler(_sqs_event(pid, attempt=1), _CONTEXT)

    assert store.get_project(pid).status == ProjectStatus.IN_PROGRESS