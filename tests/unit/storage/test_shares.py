"""
Unit tests for shares in storyboard_store: sharing a project with a user, changing or ending it, and listing what's shared.

Runs against moto's fakes of DynamoDB and S3 (see tests/unit/conftest.py), so no AWS calls are made.
"""
import pytest

from taleboard.schema.sharing import ShareRole
from taleboard.storage.storyboard_store import StoryboardStore

OWNER = "owner"
VIEWER = "viewer"


@pytest.fixture
def boards(aws):
    return StoryboardStore.from_env()


def test_a_share_is_read_back_and_listed_for_its_grantee(boards):
    """
    Verifies that a share round-trips, and the project is listed for its grantee -- but not as one of theirs.
    """
    project = boards.create_project("Lighthouse", OWNER)

    share = boards.share_project(project.project_id, VIEWER, ShareRole.VIEWER, granted_by=OWNER)

    assert boards.get_share(project.project_id, VIEWER) == share
    assert boards.list_shared_with(VIEWER) == [(project, share)]
    assert boards.list_projects(VIEWER) == []
    assert boards.list_projects(OWNER) == [project]  # The share isn't one of the owner's projects either


def test_sharing_again_changes_the_role_rather_than_adding_a_second_share(boards):
    """
    Verifies that a project has at most one share per user.
    """
    project = boards.create_project("Lighthouse", OWNER)
    boards.share_project(project.project_id, VIEWER, ShareRole.VIEWER, granted_by=OWNER)

    boards.share_project(project.project_id, VIEWER, ShareRole.EDITOR, granted_by=OWNER)

    assert [s.role for s in boards.list_shares(project.project_id)] == [ShareRole.EDITOR]


def test_shared_projects_are_listed_most_recently_shared_first(boards):
    """
    Verifies the order of the shared list.
    """
    first = boards.create_project("First", OWNER)
    second = boards.create_project("Second", OWNER)
    boards.share_project(first.project_id, VIEWER, ShareRole.VIEWER, granted_by=OWNER)
    boards.share_project(second.project_id, VIEWER, ShareRole.VIEWER, granted_by=OWNER)

    assert [p.name for p, _ in boards.list_shared_with(VIEWER)] == ["Second", "First"]


def test_unsharing_removes_it_and_is_harmless_twice(boards):
    """
    Verifies that ending a share removes it everywhere, and ending one that isn't there changes nothing.
    """
    project = boards.create_project("Lighthouse", OWNER)
    boards.share_project(project.project_id, VIEWER, ShareRole.VIEWER, granted_by=OWNER)

    boards.unshare_project(project.project_id, VIEWER)
    boards.unshare_project(project.project_id, VIEWER)

    assert boards.get_share(project.project_id, VIEWER) is None
    assert boards.list_shared_with(VIEWER) == []


def test_a_missing_project_cannot_be_shared(boards):
    """
    Verifies that a share never exists without its project.
    """
    with pytest.raises(KeyError):
        boards.share_project("no-such-project", VIEWER, ShareRole.VIEWER, granted_by=OWNER)
