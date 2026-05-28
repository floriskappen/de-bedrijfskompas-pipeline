"""Thin OpenRouter client for tagging LLM calls.

Returns a validated list of ``{family, prominence}`` capability tags. A response
that will not parse and validate against the fixed family/prominence vocabularies
and the one-entry-per-family rule is treated as an :class:`LLMError`.
"""

from __future__ import annotations

import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model — override via TAGGING_MODEL env var.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.1

# Fixed tier-1 vocabulary. Source of truth: specs/tagging/spec.md and prompts/tagging.md.
FAMILIES = frozenset({
    "software-engineering",
    "data-ai",
    "hardware-electronics",
    "mechanical-civil-engineering",
    "life-sciences",
    "earth-environmental-sciences",
    "clinical-care",
    "design-creative",
    "content-media",
    "commercial",
    "finance-accounting",
    "legal-compliance",
    "policy-public-administration",
    "operations-supply-chain",
    "people-org",
    "field-trades-operators",
    "education-training",
    "service-hospitality",
    "community-social",
})

PROMINENCE_LEVELS = frozenset({"core", "supporting", "incidental"})

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class LLMError(Exception):
    """Raised when the LLM call fails after retries."""


def resolve_model(model: str | None = None) -> str:
    """Resolve the model id: explicit arg, then env override, then default."""
    return model or os.environ.get("TAGGING_MODEL", DEFAULT_MODEL)


def call(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    retries: int = 2,
) -> list[dict]:
    """Call OpenRouter and return the validated capability-tags list.

    Raises :class:`LLMError` after *retries* transport/decode failures, or if the
    response does not validate against the family/prominence vocabularies and the
    one-entry-per-family rule.
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
            return _parse_tags(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_tags(text: str) -> list[dict]:
    """Parse the completion into a validated ``capability_tags`` list.

    Raises ``ValueError`` if the response is not a JSON object containing a
    ``capability_tags`` array of ``{family, prominence}`` entries, if any family
    is not in :data:`FAMILIES`, if any prominence is not in
    :data:`PROMINENCE_LEVELS`, or if two entries share a family.
    """
    stripped = (text or "").strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    obj = json.loads(stripped)

    if not isinstance(obj, dict):
        raise ValueError("tagging response is not a JSON object")
    tags = obj.get("capability_tags")
    if not isinstance(tags, list):
        raise ValueError("tagging response missing 'capability_tags' array")

    seen: set[str] = set()
    out: list[dict] = []
    for entry in tags:
        if not isinstance(entry, dict):
            raise ValueError(f"capability_tags entry is not an object: {entry!r}")
        family = entry.get("family")
        prominence = entry.get("prominence")
        if family not in FAMILIES:
            raise ValueError(f"unknown capability family: {family!r}")
        if prominence not in PROMINENCE_LEVELS:
            raise ValueError(f"unknown prominence: {prominence!r}")
        if family in seen:
            raise ValueError(f"duplicate family in capability_tags: {family!r}")
        seen.add(family)
        out.append({"family": family, "prominence": prominence})
    return out
