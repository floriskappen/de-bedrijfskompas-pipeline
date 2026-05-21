"""Thin OpenRouter client for content-summarization LLM calls.

Unlike fact-extraction's client, this returns the raw completion *text* (the
markdown dossier), not parsed JSON. Conversational wrappers and code fences are
stripped by :func:`strip_wrapper` before the body is persisted.
"""

from __future__ import annotations

import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model — override via CONTENT_SUMMARIZATION_MODEL env var.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.2

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n```$", re.DOTALL)
_PREAMBLE_RE = re.compile(r"^(here(?:'s| is)\b|below is\b|sure[,!.:]).*", re.IGNORECASE)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


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
