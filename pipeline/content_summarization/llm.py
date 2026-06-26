"""Thin OpenRouter client for content-summarization LLM calls.

Unlike fact-extraction's client, this returns the raw completion *text* (the
markdown dossier), not parsed JSON. Conversational wrappers and code fences are
stripped by :func:`strip_wrapper` before the body is persisted.
"""

from __future__ import annotations

import os
import random
import re
import time

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model — override via CONTENT_SUMMARIZATION_MODEL env var.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.2

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```$", re.DOTALL)
_PREAMBLE_RE = re.compile(r"^(here(?:'s| is)\b|below is\b|sure[,!.:]).*", re.IGNORECASE)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


_RETRY_BASE_SECONDS = 0.5
_RETRY_CAP_SECONDS = 30.0


def _rate_limit_response(exc: Exception) -> httpx.Response | None:
    """Return the response if *exc* is a 429/5xx HTTP status error, else None."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        status = exc.response.status_code
        if status == 429 or 500 <= status < 600:
            return exc.response
    return None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    val = response.headers.get("Retry-After")
    if not val:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _backoff_sleep(attempt: int, response: httpx.Response | None) -> None:
    """Exponential backoff with full jitter; honour ``Retry-After`` on 429/5xx.

    Full jitter (AWS-style): uniform in ``[0, min(cap, base * 2**attempt))]``.
    When the failure carries a ``Retry-After`` header, the sleep is never shorter
    than the server-requested delay. Transport/decode errors (no response) back
    off with jitter only.
    """
    upper = min(_RETRY_CAP_SECONDS, _RETRY_BASE_SECONDS * (2 ** attempt))
    sleep = random.uniform(0, upper)
    if response is not None:
        retry_after = _retry_after_seconds(response)
        if retry_after is not None:
            sleep = max(sleep, retry_after)
    time.sleep(sleep)


def resolve_model(model: str | None = None) -> str:
    """Resolve the model id: explicit arg, then env override, then default."""
    return model or os.environ.get("CONTENT_SUMMARIZATION_MODEL", DEFAULT_MODEL)


def call(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    retries: int = 2,
) -> str:
    """Call OpenRouter and return the raw completion text.

    Raises :class:`LLMError` after *retries* transport or decode failures.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    resolved_model = resolve_model(model)

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": resolved_model,
                    "messages": messages,
                    "temperature": temperature,
                    # Wafer intermittently corrupts DeepSeek V4 output values
                    # (observed as {"en": ":"}), so do not route calls to it.
                    "provider": {"ignore": ["wafer"]},
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                raise ValueError("empty completion")
            return content
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            _backoff_sleep(attempt, _rate_limit_response(exc))

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def strip_wrapper(text: str) -> str:
    """Remove a conversational preamble line and surrounding markdown fences."""
    s = text.strip()
    lines = s.split("\n")
    if lines and _PREAMBLE_RE.match(lines[0].strip()):
        lines = lines[1:]
    s = "\n".join(lines).strip()
    m = _FENCE_RE.match(s)
    if m:
        s = m.group(1).strip()
    return s
