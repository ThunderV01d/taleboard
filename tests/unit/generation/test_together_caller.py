"""
Unit tests for together_caller's retry logic.

Replaces the Together client with a fake, so no API calls are made and no API key is needed.
"""
import httpx
import pytest
from together import BadRequestError

from taleboard.generation import together_caller


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
    Verifies that a bad request still coming back once all permitted retries have been used up raises RequestRejectedError, with Together AI's error as its cause, after waiting longer each time.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the fake client.
    """
    client = _FakeClient(failures=99)
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)
    waits: list[float] = []

    with pytest.raises(together_caller.RequestRejectedError) as raised:
        together_caller._generate_with_retry({}, sleep=waits.append)
    assert isinstance(raised.value.__cause__, BadRequestError)
    assert client.calls == together_caller.BAD_REQUEST_RETRIES + 1
    assert waits == [together_caller.RETRY_BACKOFF_S * n for n in range(1, together_caller.BAD_REQUEST_RETRIES + 1)]


def test_a_content_refusal_is_never_retried(monkeypatch):
    """
    Verifies that a 400 refusing the prompt for its content raises ContentRefusedError on the first call -- retrying can't change the answer.

    Arguments:
        monkeypatch: pytest.MonkeyPatch - Used to swap in the fake client.
    """
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.together.xyz/v1/images/generations"))
    refusal = BadRequestError("Request blocked. The prompt was flagged for content that violates our safety policies.", response=response, body=None)
    calls = []

    class Refusing:
        images = None

        def generate(self, **kwargs):
            calls.append(kwargs)
            raise refusal

    client = Refusing()
    client.images = client
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)

    with pytest.raises(together_caller.ContentRefusedError):
        together_caller._generate_with_retry({}, sleep=lambda s: pytest.fail("a refusal was retried"))
    assert len(calls) == 1
