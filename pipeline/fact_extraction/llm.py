"""Thin OpenRouter client for fact-extraction LLM calls."""

from __future__ import annotations

import json
import os
import random
import re
import time

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Model options to try — override via FACT_EXTRACTION_MODEL env var
MODEL_GEMMA_4_27B = "google/gemma-4-26b-a4b-it"       # Gemma 4 26B A4B
MODEL_GEMINI_FLASH_LITE = "google/gemini-2.5-flash-lite"   # Gemini 2.5 Flash Lite

DEFAULT_MODEL = MODEL_GEMMA_4_27B
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_RETRY_BASE_SECONDS = 0.5
_RETRY_CAP_SECONDS = 30.0


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


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


def call(
    messages: list[dict],
    *,
    model: str | None = None,
    retries: int = 2,
) -> dict:
    """Call OpenRouter and return the parsed JSON response body.

    Raises LLMError after *retries* transport or decode failures.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    resolved_model = model or os.environ.get("FACT_EXTRACTION_MODEL", DEFAULT_MODEL)

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
                    "response_format": {"type": "json_object"},
                    # Wafer intermittently corrupts DeepSeek V4 output values
                    # (observed as {"en": ":"}), so do not route calls to it.
                    "provider": {"ignore": ["wafer"]},
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            _backoff_sleep(attempt, _rate_limit_response(exc))

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_json(text: str) -> dict:
    """Parse JSON, stripping markdown code fences if present."""
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1)
    return json.loads(stripped)
