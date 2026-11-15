"""Local LLM client for Ollama (`/api/chat`), with streaming and token accounting, plus a fake LLM for tests."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Protocol

import httpx

from .config import get_settings
from .retry import post_with_retry


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    ms: float = 0.0


class LLM(Protocol):
    def chat(self, messages: list[dict], *, json_mode: bool = False, temperature: float | None = None,
             max_tokens: int = 800) -> LLMResult: ...

    def stream(self, messages: list[dict], *, temperature: float | None = None, max_tokens: int = 800) -> Iterator[str | LLMResult]: ...


class OllamaLLM:
    def __init__(self, url: str, model: str, num_ctx: int, temperature: float) -> None:
        self.url, self.model, self.num_ctx, self.temperature = url.rstrip("/"), model, num_ctx, temperature
        self._client = httpx.Client(timeout=httpx.Timeout(300, connect=10))

    def _body(self, messages: list[dict], stream: bool, json_mode: bool, temperature: float | None, max_tokens: int) -> dict:
        body = {"model": self.model, "messages": messages, "stream": stream, "keep_alive": "30m",
                "options": {"temperature": self.temperature if temperature is None else temperature,
                            "num_ctx": self.num_ctx, "num_predict": max_tokens, "seed": 42}}
        if json_mode:
            body["format"] = "json"
        return body

    def chat(self, messages: list[dict], *, json_mode: bool = False, temperature: float | None = None,
             max_tokens: int = 800) -> LLMResult:
        t0 = time.perf_counter()
        r = post_with_retry(self._client, f"{self.url}/api/chat", self._body(messages, False, json_mode, temperature, max_tokens))
        d = r.json()
        return LLMResult(d["message"]["content"], d.get("prompt_eval_count", 0), d.get("eval_count", 0),
                         (time.perf_counter() - t0) * 1000)

    def stream(self, messages: list[dict], *, temperature: float | None = None, max_tokens: int = 800) -> Iterator[str | LLMResult]:
        """Yields text deltas, then one final LLMResult with the full text and token counts."""
        t0 = time.perf_counter()
        parts: list[str] = []
        with self._client.stream("POST", f"{self.url}/api/chat",
                                 json=self._body(messages, True, False, temperature, max_tokens)) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                delta = d.get("message", {}).get("content", "")
                if delta:
                    parts.append(delta)
                    yield delta
                if d.get("done"):
                    yield LLMResult("".join(parts), d.get("prompt_eval_count", 0), d.get("eval_count", 0),
                                    (time.perf_counter() - t0) * 1000)
                    return


class FakeLLM:
    """Scriptable LLM for unit tests: `responder(messages) -> str`."""

    def __init__(self, responder: Callable[[list[dict]], str] | None = None) -> None:
        self.responder = responder or (lambda m: "Answer based on the sources [1].")
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], *, json_mode: bool = False, temperature: float | None = None,
             max_tokens: int = 800) -> LLMResult:
        self.calls.append(messages)
        text = self.responder(messages)
        return LLMResult(text, sum(len(m["content"]) // 4 for m in messages), len(text) // 4, 1.0)

    def stream(self, messages: list[dict], *, temperature: float | None = None, max_tokens: int = 800) -> Iterator[str | LLMResult]:
        res = self.chat(messages)
        for word in res.text.split(" "):
            yield word + " "
        yield res


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        s = get_settings()
        _llm = FakeLLM() if s.llm_provider == "fake" else OllamaLLM(s.ollama_url, s.llm_model, s.llm_num_ctx, s.llm_temperature)
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm


def parse_json(text: str) -> dict:
    """Lenient JSON parse for LLM output (strips code fences / leading prose)."""
    text = text.strip().strip("`")
    if text.startswith("json"):
        text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
