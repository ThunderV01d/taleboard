"""
Unit tests for the generation worker.

Runs against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py), with the image generator faked -- so nothing is drawn and nothing costs anything.

Covers drawing a job's layers in order and saving each into its shot, carrying on from where an earlier delivery stopped, handing over when time runs short, layers that fail or were deleted, and the delivery-level retries.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest

from taleboard.jobs import generation_worker, worker
from taleboard.jobs.generation_worker import GenerationOutcome, run_generation_job
from taleboard.jobs.queue import GenerationQueue
from taleboard.generation.cutouts import CutoutRejectedError
from taleboard.generation.together_caller import ContentRefusedError, RequestRejectedError
from taleboard.schema.enums import Facing
from taleboard.schema.generation import GenerationJob, GenerationTask, JobStatus, TaskStatus
from taleboard.schema.layers import BackgroundLayer, CharacterLayer, PropLayer, TextLayer
from taleboard.schema.storyboard import Character, Location, Scene, Shot
from taleboard.storage.storyboard_store import StoryboardStore

REGION = "eu-west-2"
OWNER = "mara-user"


class FakeGenerator:
    """
    Stands in for the engine: "draws" a layer by giving it an image named after it, or fails as told. Records each layer drawn.
    """
    def __init__(self, project_id: str, boards, fail: dict | None = None):
        self.drawn: list[str] = []
        self.fail = fail or {}

    def generate_layer(self, layer, shot, scene, location, characters, props):
        if layer.id in self.fail:
            raise self.fail[layer.id]
        if isinstance(layer, CharacterLayer):
            characters[layer.character_id]  # A KeyError, as the engine gives, for a character gone from the registry
        self.drawn.append(layer.id)
        entry = location if isinstance(layer, BackgroundLayer) else characters.get(getattr(layer, "character_id", None)) or props.get(getattr(layer, "prop_id", None))
        return layer.model_copy(update={"image": f"drawn/{layer.id}.png", "last_generated_params": layer.current_params(shot.generation_context(scene), entry)})


@pytest.fixture
def boards(aws):
    return StoryboardStore.from_env()


@pytest.fixture
def generation_queue(aws, monkeypatch):
    url = boto3.client("sqs", region_name=REGION).create_queue(QueueName="generation-test.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
    monkeypatch.setenv("TALEBOARD_GENERATION_QUEUE_URL", url)
    return GenerationQueue.from_env()


@pytest.fixture
def story(boards):
    """
    A project with an office and Mara, one scene, and one shot holding a background, Mara and a caption -- plus a job to draw the background and Mara.

    Returns:
        SimpleNamespace - pid, scene, shot and job.
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id
    boards.create_entry(pid, Location, "Office", views={Facing.NORTH: "a window"})
    boards.create_entry(pid, Character, "Mara")
    scene = Scene(location_id="office")
    boards.create_scene(pid, scene)
    shot = Shot(scene_id=scene.id, layers=[BackgroundLayer(id="bg"), CharacterLayer(id="mara", character_id="mara", action="waving"), TextLayer(id="caption")])
    boards.create_shot(pid, shot)
    job = GenerationJob(created_at=datetime.now(timezone.utc), tasks=[
        GenerationTask(scene_id=scene.id, shot_id=shot.id, layer_id="bg"),
        GenerationTask(scene_id=scene.id, shot_id=shot.id, layer_id="mara"),
    ])
    boards.create_job(pid, job)
    return SimpleNamespace(pid=pid, scene=scene, shot=shot, job=job)


def _plenty_of_time() -> int:
    return 15 * 60 * 1000


def _run(boards, queue, story, generator=None, remaining_ms=_plenty_of_time):
    generator = generator or FakeGenerator(story.pid, boards)
    outcome = run_generation_job(boards, queue, story.pid, story.job.id, remaining_ms, make_generator=lambda pid, b: generator)
    return outcome, generator


def _image(boards, story, layer_id: str):
    shot = boards.get_shot(story.pid, story.scene.id, story.shot.id)
    return next(l for l in shot.all_layers() if l.id == layer_id).image


def test_a_job_draws_each_layer_in_order_and_saves_it_into_its_shot(boards, generation_queue, story):
    """
    Verifies the whole job: both layers drawn in order, each saved into the shot, each task done, and the job complete.
    """
    outcome, generator = _run(boards, generation_queue, story)

    job = boards.get_job(story.pid, story.job.id)
    assert outcome == GenerationOutcome.COMPLETE
    assert generator.drawn == ["bg", "mara"]
    assert (_image(boards, story, "bg"), _image(boards, story, "mara")) == ("drawn/bg.png", "drawn/mara.png")
    assert [t.status for t in job.tasks] == [TaskStatus.DONE, TaskStatus.DONE]
    assert job.status == JobStatus.COMPLETE


def test_a_retried_job_carries_on_from_its_first_pending_task(boards, generation_queue, story):
    """
    Verifies that tasks already done by an earlier delivery aren't drawn (or paid for) again.
    """
    boards.set_task_status(story.pid, story.job.id, 0, TaskStatus.DONE)

    _, generator = _run(boards, generation_queue, story)

    assert generator.drawn == ["mara"]


def test_a_finished_job_is_left_alone(boards, generation_queue, story):
    """
    Verifies that a late duplicate delivery of a finished job draws nothing.
    """
    boards.set_job_status(story.pid, story.job.id, JobStatus.COMPLETE)

    outcome, generator = _run(boards, generation_queue, story)

    assert (outcome, generator.drawn) == (GenerationOutcome.SKIPPED, [])


def test_a_job_hands_over_when_time_runs_short(boards, generation_queue, story):
    """
    Verifies that with too little time left for the second layer, the job is queued again and stays running -- and the next delivery finishes it.
    """
    times = iter([_plenty_of_time(), 0])
    outcome, generator = _run(boards, generation_queue, story, remaining_ms=lambda: next(times))

    assert (outcome, generator.drawn) == (GenerationOutcome.CONTINUED, ["bg"])
    assert boards.get_job(story.pid, story.job.id).status == JobStatus.RUNNING
    sqs = boto3.client("sqs", region_name=REGION)
    [message] = sqs.receive_message(QueueUrl=generation_queue._queue_url, AttributeNames=["All"])["Messages"]
    assert json.loads(message["Body"])["job_id"] == story.job.id

    outcome, generator = _run(boards, generation_queue, story)
    assert (outcome, generator.drawn) == (GenerationOutcome.COMPLETE, ["mara"])


def test_a_layer_that_cant_be_drawn_fails_alone_and_the_job_goes_on(boards, generation_queue, story):
    """
    Verifies that a rejected cutout fails its own task (saying why), leaves its layer a placeholder, and the rest of the job still runs.
    """
    generator = FakeGenerator(story.pid, boards, fail={"bg": CutoutRejectedError("background removal found no usable subject")})

    outcome, _ = _run(boards, generation_queue, story, generator)

    job = boards.get_job(story.pid, story.job.id)
    assert outcome == GenerationOutcome.COMPLETE
    assert (job.tasks[0].status, job.tasks[0].error) == (TaskStatus.FAILED, "background removal found no usable subject")
    assert job.tasks[1].status == TaskStatus.DONE
    assert _image(boards, story, "bg") is None


def test_a_character_gone_from_the_registry_fails_its_task(boards, generation_queue, story):
    """
    Verifies that a layer showing a character no longer in the project fails with a reason, rather than failing the job.
    """
    boards.delete_entry(story.pid, Character, "mara")

    _run(boards, generation_queue, story)

    task = boards.get_job(story.pid, story.job.id).tasks[1]
    assert task.status == TaskStatus.FAILED and "no longer in the project" in task.error


@pytest.mark.parametrize("delete", ["layer", "shot", "scene"])
def test_a_layer_deleted_before_its_turn_is_skipped(boards, generation_queue, story, delete):
    """
    Verifies that a deleted layer, shot or scene is skipped -- nothing drawn, nothing paid for.

    Arguments:
        delete: str - What's deleted before the job runs.
    """
    if delete == "layer":
        shot = boards.get_shot(story.pid, story.scene.id, story.shot.id)
        boards.save_shot(story.pid, shot.model_copy(update={"layers": [l for l in shot.layers if l.id != "mara"]}))
    elif delete == "shot":
        boards.delete_shot(story.pid, story.scene.id, story.shot.id)
    else:
        boards.delete_scene(story.pid, story.scene.id)

    _, generator = _run(boards, generation_queue, story)

    tasks = boards.get_job(story.pid, story.job.id).tasks
    assert tasks[1].status == TaskStatus.SKIPPED
    assert "mara" not in generator.drawn


def test_a_deleted_job_is_skipped(boards, generation_queue, story):
    """
    Verifies that a job deleted with its project is skipped, not an error.
    """
    boards.delete_project(story.pid)

    outcome, generator = _run(boards, generation_queue, story)

    assert (outcome, generator.drawn) == (GenerationOutcome.SKIPPED, [])


def _record(story, attempt: int = 1) -> dict:
    """
    An SQS record from the generation queue, as the worker Lambda receives it.
    """
    return {
        "body": json.dumps({"kind": "generate", "project_id": story.pid, "job_id": story.job.id}),
        "receiptHandle": "receipt-1",
        "attributes": {"ApproximateReceiveCount": str(attempt)},
    }


def test_a_failed_delivery_is_retried_until_the_last_attempt_then_the_job_fails(boards, generation_queue, story, monkeypatch):
    """
    Verifies that an error a retry might fix is re-raised (and retried a minute later), and that on the last attempt the job is marked failed instead.
    """
    retried = []
    monkeypatch.setattr(GenerationQueue, "retry_after", lambda self, receipt, delay: retried.append((receipt, delay)))
    broken = FakeGenerator(story.pid, boards, fail={"bg": RuntimeError("Together AI didn't answer")})

    with pytest.raises(RuntimeError):
        generation_worker.handle_record(_record(story, attempt=1), _plenty_of_time, make_generator=lambda pid, b: broken)
    assert retried == [("receipt-1", generation_worker.FAILED_RETRY_DELAY_S)]
    assert boards.get_job(story.pid, story.job.id).status == JobStatus.RUNNING

    generation_worker.handle_record(_record(story, attempt=generation_worker.MAX_ATTEMPTS), _plenty_of_time, make_generator=lambda pid, b: broken)
    job = boards.get_job(story.pid, story.job.id)
    assert (job.status, job.error) == (JobStatus.FAILED, "Together AI didn't answer")


def test_the_worker_hands_every_message_to_the_generation_worker(boards, generation_queue, story, monkeypatch):
    """
    Verifies the worker Lambda's entry point: each message from the generation queue goes to the generation worker.
    """
    handled = []
    monkeypatch.setattr(generation_worker, "handle_record", lambda record, remaining_ms: handled.append(json.loads(record["body"])["job_id"]))

    worker.handler({"Records": [_record(story)]}, SimpleNamespace(get_remaining_time_in_millis=_plenty_of_time))

    assert handled == [story.job.id]


def test_a_layer_the_image_model_keeps_rejecting_fails_alone_and_the_job_goes_on(boards, generation_queue, story):
    """
    Verifies that a request Together AI kept rejecting fails only its own layer (saying so), and the layers after it are still drawn -- one bad image never blocks a whole job.
    """
    rejected = RequestRejectedError("Together AI kept rejecting the request")
    rejected.__cause__ = RuntimeError("Error code: 400 - Inference error occurred")
    generator = FakeGenerator(story.pid, boards, fail={"bg": rejected})

    outcome, _ = _run(boards, generation_queue, story, generator)

    job = boards.get_job(story.pid, story.job.id)
    assert outcome == GenerationOutcome.COMPLETE
    assert job.tasks[0].status == TaskStatus.FAILED
    assert job.tasks[0].error.startswith(generation_worker.REJECTED_ERROR) and "Inference error" in job.tasks[0].error
    assert job.tasks[1].status == TaskStatus.DONE
