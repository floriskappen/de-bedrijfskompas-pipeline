"""Thin OpenRouter client for tagging LLM calls.

Returns a validated list of ``{isco_code, prominence, confidence}`` capability
tags. A response that will not parse and validate against the fixed ISCO
minor-group vocabulary and one-entry-per-code rule is treated as an
:class:`LLMError`.
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

# Fixed ISCO-08 minor-group vocabulary. Source of truth:
# specs/tagging/spec.md and prompts/tagging.md.
ISCO_MINOR_GROUPS = frozenset({
    "011",
    "021",
    "031",
    "111",
    "112",
    "121",
    "122",
    "131",
    "132",
    "133",
    "134",
    "141",
    "142",
    "143",
    "211",
    "212",
    "213",
    "214",
    "215",
    "216",
    "221",
    "222",
    "223",
    "224",
    "225",
    "226",
    "231",
    "232",
    "233",
    "234",
    "235",
    "241",
    "242",
    "243",
    "251",
    "252",
    "261",
    "262",
    "263",
    "264",
    "265",
    "311",
    "312",
    "313",
    "314",
    "315",
    "321",
    "322",
    "323",
    "324",
    "325",
    "331",
    "332",
    "333",
    "334",
    "335",
    "341",
    "342",
    "343",
    "351",
    "352",
    "411",
    "412",
    "413",
    "421",
    "422",
    "431",
    "432",
    "441",
    "511",
    "512",
    "513",
    "514",
    "515",
    "516",
    "521",
    "522",
    "523",
    "524",
    "531",
    "532",
    "541",
    "611",
    "612",
    "613",
    "621",
    "622",
    "631",
    "632",
    "633",
    "634",
    "711",
    "712",
    "713",
    "721",
    "722",
    "723",
    "731",
    "732",
    "741",
    "742",
    "751",
    "752",
    "753",
    "754",
    "811",
    "812",
    "813",
    "814",
    "815",
    "816",
    "817",
    "818",
    "821",
    "831",
    "832",
    "833",
    "834",
    "835",
    "911",
    "912",
    "921",
    "931",
    "932",
    "933",
    "941",
    "951",
    "952",
    "961",
    "962",
})

PROMINENCE_LEVELS = frozenset({"core", "supporting", "incidental"})
CONFIDENCE_LEVELS = frozenset({"high", "low"})
TAG_KEYS = frozenset({"isco_code", "prominence", "confidence"})

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
    response does not validate against the ISCO/prominence/confidence
    vocabularies and the one-entry-per-code rule.
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
                    # Wafer intermittently corrupts DeepSeek V4 output values
                    # (observed as {"en": ":"}), so do not route calls to it.
                    "provider": {"ignore": ["wafer"]},
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
    ``capability_tags`` array of ``{isco_code, prominence, confidence}``
    entries, if any code is not in :data:`ISCO_MINOR_GROUPS`, if any prominence
    or confidence is invalid, or if two entries share an ISCO code.
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
        if set(entry.keys()) != TAG_KEYS:
            raise ValueError(
                f"capability_tags entry must have exactly {sorted(TAG_KEYS)}: {entry!r}"
            )
        isco_code = entry.get("isco_code")
        prominence = entry.get("prominence")
        confidence = entry.get("confidence")
        if isco_code not in ISCO_MINOR_GROUPS:
            raise ValueError(f"unknown ISCO minor-group code: {isco_code!r}")
        if prominence not in PROMINENCE_LEVELS:
            raise ValueError(f"unknown prominence: {prominence!r}")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"unknown confidence: {confidence!r}")
        if isco_code in seen:
            raise ValueError(f"duplicate isco_code in capability_tags: {isco_code!r}")
        seen.add(isco_code)
        out.append(
            {
                "isco_code": isco_code,
                "prominence": prominence,
                "confidence": confidence,
            }
        )
    return out
