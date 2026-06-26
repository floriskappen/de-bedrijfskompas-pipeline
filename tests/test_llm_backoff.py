"""Tests for the rate-limit-aware retry backoff shared (duplicated) across the six
LLM stage clients.

Covers the spec scenarios in
``openspec/changes/parallelize-llm-calls-per-stage/specs/pipeline-architecture/spec.md``:

- **"Rate-limit retry backs off"**            -> ``test_llm_backs_off_on_429``
- **"Concurrent retries do not fire in lockstep"** -> ``test_concurrent_retries_jittered_not_in_lockstep``
"""

from __future__ import annotations

import importlib
import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import httpx
import pytest

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# (stage llm module path, extra kwargs to pass to ``call``). translation is the
# only client that requires ``expected_keys``.
_STAGES = [
    pytest.param("pipeline.fact_extraction.llm", {}, id="fact-extraction"),
    pytest.param("pipeline.content_summarization.llm", {}, id="content-summarization"),
    pytest.param("pipeline.tagline_extraction.llm", {}, id="tagline-extraction"),
    pytest.param("pipeline.global_scoring.llm", {}, id="global-scoring"),
    pytest.param("pipeline.tagging.llm", {}, id="tagging"),
    pytest.param("pipeline.translation.llm", {"expected_keys": {"k"}}, id="translation"),
]


def _resp_429(retry_after: str | None = "2") -> httpx.Response:
    """A 429 response with an optional ``Retry-After`` header, request attached."""
    headers = {"Retry-After": retry_after} if retry_after else {}
    return httpx.Response(
        429, headers=headers, request=httpx.Request("POST", OPENROUTER_URL)
    )


@pytest.mark.parametrize("module_path,extra_kwargs", _STAGES)
def test_llm_backs_off_on_429(
    module_path: str, extra_kwargs: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenario: Rate-limit retry backs off.

    A 429 with ``Retry-After: 2`` is retried (``retries=2`` default -> 2 sleeps),
    and every sleep is at least the server-requested 2 seconds. Without backoff
    the loop would retry immediately and never sleep.
    """
    mod = importlib.import_module(module_path)
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(mod.httpx, "post", lambda *a, **k: _resp_429("2"))

    with pytest.raises(mod.LLMError):
        mod.call([{"role": "user", "content": "hi"}], **extra_kwargs)

    assert len(sleeps) == 2  # 3 attempts -> 2 sleeps before retries
    assert all(s >= 2.0 for s in sleeps)  # honours Retry-After: never shorter than 2s


def test_concurrent_retries_jittered_not_in_lockstep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario: Concurrent retries do not fire in lockstep.

    Several concurrent requests all receive 429 (no Retry-After, so pure jitter).
    Jitter (``random.uniform``) produces a distinct sleep duration per call, so the
    retries are spaced rather than firing simultaneously. ``random.uniform`` is
    stubbed to a thread-safe counter so the assertion is deterministic.
    """
    from pipeline.tagline_extraction import llm as mod

    counter = itertools.count()
    lock = threading.Lock()

    def _unique_uniform(_low: float, _high: float) -> float:
        with lock:
            return float(next(counter))

    monkeypatch.setattr(mod.random, "uniform", _unique_uniform)
    monkeypatch.setattr(mod.httpx, "post", lambda *a, **k: _resp_429(None))
    sleeps: list[float] = []
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))

    def _one(_: object) -> None:
        try:
            mod.call([{"role": "user", "content": "hi"}], retries=1)
        except mod.LLMError:
            pass

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(_one, range(4)))

    # 4 calls x 1 retry each = 4 sleeps, each with a distinct jittered value.
    assert len(sleeps) == 4
    assert len(set(sleeps)) == 4
