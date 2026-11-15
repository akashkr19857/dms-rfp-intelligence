"""Retry for calls to the local Ollama server.

A laptop GPU can briefly reset (Windows TDR) under memory pressure; Ollama then answers 500/400 for a few seconds while
it reloads the model. Retrying with back-off turns that into a short pause instead of a failed 10-minute analysis."""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger("rfp.retry")
DELAYS = (3.0, 8.0, 20.0, 40.0)


def post_with_retry(client: httpx.Client, url: str, json: dict) -> httpx.Response:
    for attempt, delay in enumerate((*DELAYS, None)):
        try:
            r = client.post(url, json=json)
            if r.status_code < 400 or (r.status_code < 500 and r.status_code != 400) or delay is None:
                r.raise_for_status()
                return r
            log.warning("Ollama returned %s (attempt %d), retrying in %.0fs", r.status_code, attempt + 1, delay)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if delay is None:
                raise
            log.warning("Ollama unreachable (%s), retrying in %.0fs", type(exc).__name__, delay)
        time.sleep(delay)
    raise RuntimeError("unreachable")
