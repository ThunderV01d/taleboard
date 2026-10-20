"""
Shared fixtures for the API tests -- a fake-backed store, and a test client that uses it and sends a valid API key.

Attributes:
    TEST_API_KEY: str - The API key the test client sends, and the app is told to expect.
"""
import pytest
from fastapi.testclient import TestClient

from taleboard.api.app import app, get_api_key
from taleboard.api.deps import get_boards
from taleboard.storage.storyboard_store import StoryboardStore

TEST_API_KEY = "test-api-key"


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
def client(boards):
    """
    A test client whose store and expected API key are fakes, and which sends that key on every request.

    Arguments:
        boards: StoryboardStore - Fake-backed store.

    Returns:
        TestClient - Client for the API.
    """
    app.dependency_overrides[get_boards] = lambda: boards
    app.dependency_overrides[get_api_key] = lambda: TEST_API_KEY
    yield TestClient(app, headers={"X-API-Key": TEST_API_KEY})
    app.dependency_overrides.clear()
