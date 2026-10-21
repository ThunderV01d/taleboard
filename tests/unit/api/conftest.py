"""
Shared fixtures for the API tests -- a fake-backed store, and a test client that uses it as a signed-in user.

Attributes:
    TEST_USER_ID: str - The user the test client is signed in as.
"""
import pytest
from fastapi.testclient import TestClient

from taleboard.api.app import app
from taleboard.api.deps import get_boards, get_user_id
from taleboard.storage.storyboard_store import StoryboardStore

TEST_USER_ID = "test-user"


@pytest.fixture
def boards(aws):
    """
    A StoryboardStore backed by the shared fakes.

    Arguments:
        aws: tuple[ProjectStore,JobQueue] - The shared fakes (they also set the TALEBOARD_* environment variables).

    Returns:
        StoryboardStore - A store backed by the fakes.
    """
    return StoryboardStore.from_env()


@pytest.fixture
def user_id() -> str:
    """
    The user the test client is signed in as.

    Returns:
        str - TEST_USER_ID.
    """
    return TEST_USER_ID


@pytest.fixture
def client(boards):
    """
    A test client whose store is the fakes, signed in as TEST_USER_ID -- standing in for API Gateway's JWT authorizer, which doesn't run in tests.

    Arguments:
        boards: StoryboardStore - Fake-backed store.

    Returns:
        TestClient - Client for the API.
    """
    app.dependency_overrides[get_boards] = lambda: boards
    app.dependency_overrides[get_user_id] = lambda: TEST_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()
