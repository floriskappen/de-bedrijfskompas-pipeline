"""Thin OpenRouter client for tagline-extraction LLM calls.

Returns a parsed ``{"en": ..., "nl": ...}`` object (like fact-extraction's client),
not raw text. A response that will not parse into an object with non-empty ``en``
and ``nl`` strings is treated as an :class:`LLMError`.
"""

from __future__ import annotations

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model — override via TAGLINE_EXTRACTION_MODEL env var.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.2

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


def resolve_model(model: str | None = None) -> str:
    """Resolve the model id: explicit arg, then env override, then default."""
    return model or os.environ.get("TAGLINE_EXTRACTION_MODEL", DEFAULT_MODEL)


def call(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    retries: int = 2,
) -> dict:
    """Call OpenRouter and return the parsed ``{en, nl}`` object.

    Raises :class:`LLMError` after *retries* transport/decode failures, or if the
    response lacks non-empty ``en`` and ``nl`` string members.
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
                    "response_format": {"type": "json_object"},
                },
                timeout=60.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_tagline(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_tagline(text: str) -> dict:
    """Parse the completion into ``{en, nl}``, stripping a code fence if present.

    Raises ``ValueError`` if the object lacks non-empty ``en`` and ``nl`` strings,
    so the caller's retry/​error path treats it as a failed call.
    """
    stripped = (text or "").strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    obj = json.loads(stripped)

    if not isinstance(obj, dict):
        raise ValueError("tagline response is not a JSON object")
    en, nl = obj.get("en"), obj.get("nl")
    if not isinstance(en, str) or not en.strip():
        raise ValueError("tagline response missing non-empty 'en'")
    if not isinstance(nl, str) or not nl.strip():
        raise ValueError("tagline response missing non-empty 'nl'")
    return {"en": en.strip(), "nl": nl.strip()}
