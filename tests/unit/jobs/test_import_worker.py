"""
Unit tests for the import worker.

Runs against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py), with every LLM call answered by a fake -- so nothing costs anything.

Covers importing a story into a project, queueing the job that draws it (or not), a retry starting cleanly, stories that can't be imported, the delivery-level retries, and the worker routing import messages here.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import boto3
import pytest

from taleboard.jobs import import_worker, worker
from taleboard.jobs.generation_worker import FAILED_RETRY_DELAY_S, MAX_ATTEMPTS
from taleboard.jobs.import_worker import run_import_job
from taleboard.jobs.queue import GenerationQueue
from taleboard.parsing.llm_schemas import LLMCastOutput, LLMJudgeOutput, LLMLocationsOutput, LLMPropsOutput, LLMScenesOutput
from taleboard.schema.generation import GenerationJob, JobKind, JobStatus
from taleboard.schema.layers import GroupLayer
from taleboard.schema.storyboard import Character, Location, Scene, Shot
from taleboard.storage.storyboard_store import StoryboardStore

REGION = "eu-west-2"
OWNER = "mara-user"
STORY = "Mara read the letter.\n\nTomas waited on the quay."

_VIEWS = {"north": "the lens", "east": "a window", "south": "the stairs", "west": "shelves"}

RESPONSES = {
    LLMCastOutput: json.dumps({"characters": [
        {"name": "Mara", "description": "a woman in an oilskin coat", "aliases": []},
        {"name": "Tomas", "description": "a man in a wool coat", "aliases": []},
    ]}),
    LLMPropsOutput: json.dumps({"props": [{"name": "Letter", "description": "a folded letter"}]}),
    LLMLocationsOutput: json.dumps({"locations": [
        {"name": "Lamp Room", "setting": "interior", "features": [], "description": "a round stone room", "views": _VIEWS},
        {"name": "Quay", "setting": "exterior", "features": [], "description": "a stone quay", "views": _VIEWS},
    ]}),
    LLMJudgeOutput: json.dumps({"texts": []}),
}

SCENES = json.dumps({"scenes": [
    {"first_paragraph": 0, "location_id": "lamp_room", "time_of_day": "night", "atmosphere": "stormy", "name": "Lamp room", "description": "..."},
    {"first_paragraph": 1, "location_id": "quay", "time_of_day": "night", "atmosphere": "rainy", "name": "Quay", "description": "..."},
]})


def _shots(character_id: str, held: str | None = None) -> str:
    """
    A paragraph's breakdown: one shot of one character (holding a prop, if given).
    """
    return json.dumps({"shots": [{
        "description": "...", "facing": "north", "details": "", "shot_size": "medium", "angle": "eye_level", "duration_s": 2.0,
        "regions": [{"character_id": character_id, "position": "mid_center", "size": "medium", "orientation": "right", "action": "standing"}],
        "props": [{"prop_id": held, "position": "mid_left", "size": "small", "orientation": "towards_camera", "held_by": character_id}] if held else [],
    }]})


def fake_make_caller(cast: str | None = None):
    """
    A fake LLM caller builder: canned answers for each schema, and the two paragraphs' shots in turn.

    Arguments:
        cast: str - A different cast extraction answer. Defaults to None (Mara and Tomas).

    Returns:
        MakeCaller - The fake.
    """
    shots = iter([_shots("mara", held="letter"), _shots("tomas")])

    def make_caller(schema_model):
        def call_llm(prompt: str) -> str:
            if issubclass(schema_model, LLMScenesOutput):
                return SCENES
            if schema_model is LLMCastOutput and cast is not None:
                return cast
            return RESPONSES.get(schema_model) or next(shots)
        return call_llm
    return make_caller


@pytest.fixture
def boards(aws):
    return StoryboardStore.from_env()


@pytest.fixture
def generation_queue(aws, monkeypatch):
    url = boto3.client("sqs", region_name=REGION).create_queue(QueueName="import-test.fifo", Attributes={"FifoQueue": "true"})["QueueUrl"]
    monkeypatch.setenv("TALEBOARD_GENERATION_QUEUE_URL", url)
    return GenerationQueue.from_env()


def _import_job(boards, draw: bool = True, story: str = STORY) -> SimpleNamespace:
    """
    An empty project, with an import job for the story saved (as the import route does).
    """
    pid = boards.create_project("Lighthouse", OWNER).project_id
    job = GenerationJob(created_at=datetime.now(timezone.utc), kind=JobKind.IMPORT, draw=draw)
    boards.save_story(pid, job.id, story)
    boards.create_job(pid, job)
    return SimpleNamespace(pid=pid, job=job)


def _messages(queue: GenerationQueue) -> list[dict]:
    sqs = boto3.client("sqs", region_name=REGION)
    return [json.loads(m["Body"]) for m in sqs.receive_message(QueueUrl=queue._queue_url, MaxNumberOfMessages=10).get("Messages", [])]


def test_an_import_writes_the_story_into_the_project(boards, generation_queue):
    """
    Verifies the whole import: registries, a scene per scene of the story with its shots, the held letter grouped with Mara, and the job complete.
    """
    imported = _import_job(boards, draw=False)

    run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller())

    assert {c.id for c in boards.list_entries(imported.pid, Character)} == {"mara", "tomas"}
    scenes = sorted(boards.list_scenes(imported.pid), key=lambda s: s.order)
    assert [(s.location_id, s.atmosphere) for s in scenes] == [("lamp_room", "stormy"), ("quay", "rainy")]
    [reading] = boards.list_shots(imported.pid, scenes[0].id)
    assert isinstance(reading.layers[1], GroupLayer) and [c.type for c in reading.layers[1].children] == ["character", "prop"]
    assert boards.get_job(imported.pid, imported.job.id).status == JobStatus.COMPLETE


def test_drawing_everything_queues_one_job_for_every_layer_behind_the_import(boards, generation_queue):
    """
    Verifies that an import asked to draw everything queues a generation job whose tasks are every generated layer, in story order.
    """
    imported = _import_job(boards, draw=True)

    drawing = run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller())

    shots = [s for scene in sorted(boards.list_scenes(imported.pid), key=lambda s: s.order) for s in boards.list_shots(imported.pid, scene.id)]
    expected = [layer.id for shot in shots for layer in shot.all_layers() if layer.type != "group"]
    assert [t.layer_id for t in boards.get_job(imported.pid, drawing.id).tasks] == expected  # Background, Mara, letter, background, Tomas
    assert len(expected) == 5
    assert _messages(generation_queue) == [{"kind": "generate", "project_id": imported.pid, "job_id": drawing.id}]


def test_an_import_not_asked_to_draw_queues_nothing(boards, generation_queue):
    """
    Verifies that with draw off, the layers are left as placeholders and no generation job is made.
    """
    imported = _import_job(boards, draw=False)

    assert run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller()) is None
    assert [j.kind for j in boards.list_jobs(imported.pid)] == [JobKind.IMPORT]
    assert _messages(generation_queue) == []


def test_a_retried_import_replaces_what_an_earlier_attempt_wrote(boards, generation_queue):
    """
    Verifies that what a failed earlier delivery left behind (a scene and an entry) is cleared, so the project holds the story once.
    """
    imported = _import_job(boards, draw=False)
    boards.create_entry(imported.pid, Location, "Lamp Room")
    boards.create_scene(imported.pid, Scene(location_id="lamp_room"))

    run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller())

    assert len(boards.list_scenes(imported.pid)) == 2
    assert {l.id for l in boards.list_entries(imported.pid, Location)} == {"lamp_room", "quay"}


def test_a_story_with_no_characters_fails_at_once(boards, generation_queue):
    """
    Verifies that a story that can't be broken down (no characters) fails the job with the reason -- not retried, nothing written.
    """
    imported = _import_job(boards)

    run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller(cast=json.dumps({"characters": []})))

    job = boards.get_job(imported.pid, imported.job.id)
    assert job.status == JobStatus.FAILED and "no characters" in job.error
    assert boards.list_scenes(imported.pid) == []


def test_a_finished_import_is_left_alone(boards, generation_queue):
    """
    Verifies that a late duplicate delivery of a finished import writes nothing.
    """
    imported = _import_job(boards)
    boards.set_job_status(imported.pid, imported.job.id, JobStatus.COMPLETE)

    run_import_job(boards, generation_queue, imported.pid, imported.job.id, fake_make_caller())

    assert boards.list_scenes(imported.pid) == []


def _record(imported, attempt: int = 1) -> dict:
    return {
        "body": json.dumps({"kind": "import", "project_id": imported.pid, "job_id": imported.job.id}),
        "receiptHandle": "receipt-1",
        "attributes": {"ApproximateReceiveCount": str(attempt)},
    }


def test_a_failed_delivery_is_retried_until_the_last_attempt_then_the_import_fails(boards, generation_queue, monkeypatch):
    """
    Verifies that an error a retry might fix (Bedrock not answering) is re-raised and retried a minute later, and that on the last attempt the job is marked failed instead.
    """
    retried = []
    monkeypatch.setattr(GenerationQueue, "retry_after", lambda self, receipt, delay: retried.append((receipt, delay)))
    imported = _import_job(boards)

    def unreachable(schema_model):
        def call_llm(prompt: str) -> str:
            raise RuntimeError("Bedrock didn't answer")
        return call_llm

    with pytest.raises(RuntimeError):
        import_worker.handle_record(_record(imported), make_caller=unreachable)
    assert retried == [("receipt-1", FAILED_RETRY_DELAY_S)]

    import_worker.handle_record(_record(imported, attempt=MAX_ATTEMPTS), make_caller=unreachable)
    job = boards.get_job(imported.pid, imported.job.id)
    assert (job.status, job.error) == (JobStatus.FAILED, "Bedrock didn't answer")


def test_the_worker_hands_import_messages_to_the_import_worker(boards, generation_queue, monkeypatch):
    """
    Verifies the worker Lambda's routing: an import message goes to the import worker, a generation message to the generation worker.
    """
    handled = []
    monkeypatch.setattr(import_worker, "handle_record", lambda record: handled.append("import"))
    monkeypatch.setattr(worker.generation_worker, "handle_record", lambda record, remaining_ms: handled.append("generate"))
    imported = _import_job(boards)
    generate = {**_record(imported), "body": json.dumps({"kind": "generate", "project_id": imported.pid, "job_id": "j1"})}

    worker.handler({"Records": [_record(imported), generate]}, SimpleNamespace(get_remaining_time_in_millis=lambda: 900_000))

    assert handled == ["import", "generate"]
