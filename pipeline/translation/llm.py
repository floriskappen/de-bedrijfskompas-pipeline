"""Thin OpenRouter client for translation LLM calls.

Accepts a dict of {key: en_text} and returns {key: nl_text}.
A response that cannot be parsed into a dict with non-empty Dutch strings for
all submitted keys is treated as an :class:`LLMError`.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.1

# Explicit registry of (source-stage-id, dotted-path) pairs to translate.
# A "*" segment in a path matches all dict keys at that level.
TRANSLATION_TARGETS: list[tuple[str, str]] = [
    ("tagline-extraction", "tagline"),
    ("global-scoring", "scores.*.reason"),
]

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "translation.md"


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


def resolve_model(model: str | None = None) -> str:
    """Resolve the model id: explicit arg, then env override, then default."""
    return model or os.environ.get("TRANSLATION_MODEL", DEFAULT_MODEL)


def resolve_targets(record: dict, path: str) -> dict[str, str]:
    """Expand a dotted path (with optional ``*`` wildcard) against a JSON record.

    Returns a flat dict of {resolved_path: en_text} for each non-empty string
    found. Missing or non-string values are silently skipped.

    Examples::

        resolve_targets({"tagline": {"en": "A shop."}}, "tagline")
        # → {"tagline": "A shop."}

        resolve_targets({"scores": {"substance": {"reason": {"en": "Because."}}}},
                        "scores.*.reason")
        # → {"scores.substance.reason": "Because."}
    """
    parts = path.split(".")
    return dict(_walk(record, parts, []))


def _walk(obj: object, parts: list[str], prefix: list[str]) -> list[tuple[str, str]]:
    if not parts:
        if isinstance(obj, str) and obj.strip():
            return [(".".join(prefix), obj.strip())]
        if isinstance(obj, dict):
            en = obj.get("en")
            if isinstance(en, str) and en.strip():
                return [(".".join(prefix), en.strip())]
        return []

    head, *tail = parts
    if not isinstance(obj, dict):
        return []

    if head == "*":
        results: list[tuple[str, str]] = []
        for key, val in obj.items():
            results.extend(_walk(val, tail, prefix + [key]))
        return results

    if head not in obj:
        return []
    return _walk(obj[head], tail, prefix + [head])


def call(
    messages: list[dict],
    *,
    expected_keys: set[str],
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    retries: int = 2,
) -> dict[str, str]:
    """Call OpenRouter and return {key: nl_text} for all expected_keys.

    Raises :class:`LLMError` after *retries* failures or if the response is
    missing or has empty Dutch strings for any expected key.
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
            return _parse_translations(content, expected_keys)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break

    raise LLMError(f"translation call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_translations(text: str, expected_keys: set[str]) -> dict[str, str]:
    """Parse and validate the completion into {key: nl_text}.

    Raises ``ValueError`` if any expected key is missing or has an empty value.
    """
    stripped = (text or "").strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    obj = json.loads(stripped)

    if not isinstance(obj, dict):
        raise ValueError("translation response is not a JSON object")

    result: dict[str, str] = {}
    for key in expected_keys:
        val = obj.get(key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"translation response missing non-empty value for key {key!r}")
        result[key] = val.strip()
    return result


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_messages(targets: dict[str, str]) -> list[dict]:
    """Build the chat messages for a translation call."""
    payload = json.dumps(targets, ensure_ascii=False)
    return [
        {"role": "system", "content": load_prompt()},
        {"role": "user", "content": payload},
    ]
