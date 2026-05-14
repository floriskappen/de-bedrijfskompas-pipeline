"""Thin OpenRouter client for fact-extraction LLM calls."""

from __future__ import annotations

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Model options to try — override via FACT_EXTRACTION_MODEL env var
MODEL_GEMMA_4_27B = "google/gemma-4-26b-a4b-it"       # Gemma 4 26B A4B
MODEL_GEMINI_FLASH_LITE = "google/gemini-2.5-flash-lite"   # Gemini 2.5 Flash Lite

DEFAULT_MODEL = MODEL_GEMMA_4_27B
_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


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

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_json(text: str) -> dict:
    """Parse JSON, stripping markdown code fences if present."""
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1)
    return json.loads(stripped)
