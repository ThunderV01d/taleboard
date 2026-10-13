"""
Unit tests for dead-lettered job recovery.

Runs against moto's fakes of DynamoDB, S3 and SQS (see tests/unit/conftest.py).
"""
import json

from taleboard.jobs import dead_letters
from taleboard.schema.enums import ProjectStatus


def _event(project_id: str, job_id: str) -> dict:
    """
    Builds an SQS event as the dead-letter queue delivers it.

    Arguments:
        project_id: str - Unique project ID.
        job_id: str - Unique render job ID.

    Returns:
        dict - SQS event holding one dead-lettered message.
    """
    return {"Records": [{"body": json.dumps({"project_id": project_id, "job_id": job_id})}]}


def _job_in_progress(store) -> str:
    """
    Creates a project whose job "job-1" is mid-render.

    Arguments:
        store: ProjectStore - Store to create the project in.

    Returns:
        str - The project's ID.
    """
    project = store.create_project("Lighthouse")
    store.submit_story(project.project_id, "job-1", "Alice waved.")
    store.claim_job(project.project_id, "job-1")
    return project.project_id


def test_a_dead_lettered_job_in_progress_is_marked_failed(store):
    """
    Verifies that a job stuck in progress is marked failed, so the user can resubmit.

    Arguments:
        store: ProjectStore - Fake-backed store.
    """
    pid = _job_in_progress(store)

    dead_letters.handler(_event(pid, "job-1"), None)

    project = store.get_project(pid)
    assert project.status == ProjectStatus.FAILED
    assert project.error == dead_letters.DEAD_LETTER_ERROR


def test_a_dead_lettered_duplicate_of_a_completed_job_changes_nothing(store):
    """
    Verifies that a dead-lettered duplicate never turns a completed job into a failed one.

    Arguments:
        store: ProjectStore - Fake-backed store.
    """
    pid = _job_in_progress(store)
    store.finish_job(pid, "job-1", ProjectStatus.COMPLETE)

    dead_letters.handler(_event(pid, "job-1"), None)

    assert store.get_project(pid).status == ProjectStatus.COMPLETE


def test_a_dead_lettered_message_for_a_superseded_job_changes_nothing(store):
    """
    Verifies that a dead-lettered message for an old job never touches the project's current job.

    Arguments:
        store: ProjectStore - Fake-backed store.
    """
    pid = _job_in_progress(store)

    dead_letters.handler(_event(pid, "some-older-job"), None)

    assert store.get_project(pid).status == ProjectStatus.IN_PROGRESS