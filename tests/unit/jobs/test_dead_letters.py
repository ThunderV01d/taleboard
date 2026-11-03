"""
Unit tests for dead-lettered job recovery.

Runs against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py).
"""
import json
from datetime import datetime, timezone

from taleboard.jobs import dead_letters
from taleboard.schema.generation import GenerationJob, GenerationTask, JobStatus, TaskStatus
from taleboard.storage.storyboard_store import StoryboardStore


def _generation_job(status: JobStatus) -> tuple[StoryboardStore, str, str]:
    """
    Creates a project with a generation job in the given state, one of whose tasks is done.

    Arguments:
        status: JobStatus - The job's status.

    Returns:
        tuple[StoryboardStore,str,str] - The store, the project's ID and the job's ID.
    """
    boards = StoryboardStore.from_env()
    pid = boards.create_project("Lighthouse", "mara-user").project_id
    job = GenerationJob(created_at=datetime.now(timezone.utc), tasks=[GenerationTask(scene_id="s", shot_id="sh", layer_id="l", status=TaskStatus.DONE)])
    boards.create_job(pid, job)
    boards.set_job_status(pid, job.id, status)
    return boards, pid, job.id


def _event(project_id: str, job_id: str) -> dict:
    """
    Builds an SQS event as the dead-letter queue delivers it.

    Arguments:
        project_id: str - Unique project ID.
        job_id: str - Unique generation job ID.

    Returns:
        dict - SQS event holding one dead-lettered message.
    """
    return {"Records": [{"body": json.dumps({"kind": "generate", "project_id": project_id, "job_id": job_id})}]}


def test_a_dead_lettered_job_is_marked_failed_and_keeps_its_finished_tasks(aws):
    """
    Verifies that a generation job stuck running is marked failed (so the editor stops waiting on it), with its done tasks kept.

    Arguments:
        aws: None - The shared fakes.
    """
    boards, pid, job_id = _generation_job(JobStatus.RUNNING)

    dead_letters.handler(_event(pid, job_id), None)

    job = boards.get_job(pid, job_id)
    assert (job.status, job.error) == (JobStatus.FAILED, dead_letters.DEAD_LETTER_ERROR)
    assert job.tasks[0].status == TaskStatus.DONE


def test_a_dead_lettered_job_that_finished_or_was_deleted_is_left_alone(aws):
    """
    Verifies that a job that completed anyway stays complete, and one deleted with its project is ignored.

    Arguments:
        aws: None - The shared fakes.
    """
    boards, pid, job_id = _generation_job(JobStatus.COMPLETE)

    dead_letters.handler(_event(pid, job_id), None)
    dead_letters.handler(_event(pid, "deleted-job"), None)

    assert boards.get_job(pid, job_id).status == JobStatus.COMPLETE
    assert len(boards.list_jobs(pid)) == 1
