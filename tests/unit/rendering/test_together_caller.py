"""
Unit tests for together_caller's retry logic.

Replaces the Together client with a fake, so no API calls are made and no API key is needed.
"""
import httpx
import pytest
from together import BadRequestError

from taleboard.rendering import together_caller


def _bad_request() -> BadRequestError:
    """
    Builds the kind of 400 error Together AI returns intermittently for valid requests.

    Returns:
        BadRequestError - A Together SDK bad request error.
    """
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.together.xyz/v1/images/generations"))
    return BadRequestError("Invalid value for 'width' parameter.", response=response, body=None)


class _FakeClient:
    """
    Fake Together client that fails a set number of times before succeeding.

    Doubles as its own 'images' attribute, so client.images.generate resolves to the generate method below.

    Attributes:
        failures: int - Number of calls that raise a bad request before calls start succeeding.
        calls: int - Number of generate calls made so far.
        images: _FakeClient - The client itself.
    """
    def __init__(self, failures: int):
        """
        Sets up the fake client.

        Arguments:
            failures: int - Number of calls that raise a bad request before calls start succeeding.
        """
        self.failures = failures
        self.calls = 0
        self.images = self

    def generate(self, **kwargs):
        """
        Counts the call, raising a bad request until the permitted number of failures has been used up.

        Arguments:
            kwargs: dict - Keyword arguments of the generate call (ignored).

        Returns:
            str - "ok", once the permitted failures have been used up.
        """
        self.calls += 1
        if self.calls <= self.failures:
            raise _bad_request()
        return "ok"


def test_transient_bad_request_is_retried(monkeypatch):
    """
    Verifies that a bad request is retried, and that the call succeeds once the errors stop.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the fake client.
    """
    client = _FakeClient(failures=2)
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)

    assert together_caller._generate_with_retry({}, sleep=lambda s: None) == "ok"
    assert client.calls == 3


def test_persistent_bad_request_is_raised_after_retries(monkeypatch):
    """
    Verifies that a bad request is raised once all permitted retries have been used up.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the fake client.
    """
    client = _FakeClient(failures=99)
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)

    with pytest.raises(BadRequestError):
        together_caller._generate_with_retry({}, sleep=lambda s: None)
    assert client.calls == together_caller.BAD_REQUEST_RETRIES + 1
