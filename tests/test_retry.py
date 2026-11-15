from __future__ import annotations

import httpx
import pytest

from app import retry


def _client(statuses: list[int]) -> tuple[httpx.Client, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        code = statuses[min(len(calls), len(statuses) - 1)]
        calls.append(code)
        return httpx.Response(code, json={"ok": code == 200})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(retry, "DELAYS", (0.0, 0.0, 0.0, 0.0))
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)


def test_retries_transient_gpu_errors_then_succeeds():
    client, calls = _client([500, 400, 200])
    r = retry.post_with_retry(client, "http://ollama/api/chat", {})
    assert r.status_code == 200 and calls == [500, 400, 200]


def test_gives_up_after_all_attempts():
    client, calls = _client([500])
    with pytest.raises(httpx.HTTPStatusError):
        retry.post_with_retry(client, "http://ollama/api/chat", {})
    assert len(calls) == len(retry.DELAYS) + 1


def test_does_not_retry_permanent_client_errors():
    client, calls = _client([404])
    with pytest.raises(httpx.HTTPStatusError):
        retry.post_with_retry(client, "http://ollama/api/chat", {})
    assert calls == [404]
