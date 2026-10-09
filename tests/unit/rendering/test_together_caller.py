import httpx
import pytest
from together import BadRequestError

from taleboard.rendering import together_caller


def _bad_request() -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.together.xyz/v1/images/generations"))
    return BadRequestError("Invalid value for 'width' parameter.", response=response, body=None)


class _FakeClient:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0
        self.images = self

    def generate(self, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise _bad_request()
        return "ok"


def test_transient_bad_request_is_retried(monkeypatch):
    client = _FakeClient(failures=2)
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)

    assert together_caller._generate_with_retry({}, sleep=lambda s: None) == "ok"
    assert client.calls == 3


def test_persistent_bad_request_is_raised_after_retries(monkeypatch):
    client = _FakeClient(failures=99)
    monkeypatch.setattr(together_caller, "_get_client", lambda: client)

    with pytest.raises(BadRequestError):
        together_caller._generate_with_retry({}, sleep=lambda s: None)
    assert client.calls == together_caller.BAD_REQUEST_RETRIES + 1