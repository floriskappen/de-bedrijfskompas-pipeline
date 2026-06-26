"""Thin OpenRouter client for global-scoring LLM calls.

Returns a validated five-axis object — one entry per axis in :data:`AXES`, each
``{"score": int|None, "evidence": <level>, "reason": {"en": str}}``.
A response that will not parse and validate into that shape is treated as an
:class:`LLMError`, so malformed/partial output never reaches the company record.
"""

from __future__ import annotations

import json
import os
import random
import re
import time

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default model — override via GLOBAL_SCORING_MODEL env var.
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_TEMPERATURE = 0.1

# The five structural axes from docs/GLOBAL_SCORING_FRAMEWORK.md, in framework order.
AXES = ("substance", "ecology", "power", "embeddedness", "posture")

# Evidence vocabulary. A null score occurs only with ``no_signal`` and vice versa.
EVIDENCE_LEVELS = ("well_evidenced", "partial", "no_signal")

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


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
    return model or os.environ.get("GLOBAL_SCORING_MODEL", DEFAULT_MODEL)


def call(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    retries: int = 2,
) -> dict:
    """Call OpenRouter and return the validated five-axis object.

    Raises :class:`LLMError` after *retries* transport/decode failures, or if the
    response does not validate into the five-axis schema.
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
                timeout=90.0,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_scores(content)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            if attempt == retries:
                break
            _backoff_sleep(attempt, _rate_limit_response(exc))

    raise LLMError(f"LLM call failed after {retries + 1} attempts: {last_exc}") from last_exc


def _parse_scores(text: str) -> dict:
    """Parse and validate the completion into the five-axis schema.

    Strips a code fence if present. Raises ``ValueError`` (which the caller treats
    as a failed call) on any structural problem so partial output is never trusted.
    """
    stripped = (text or "").strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    obj = json.loads(stripped)

    if not isinstance(obj, dict):
        raise ValueError("scores response is not a JSON object")

    # Accept either the bare axis map or a {"scores": {...}} wrapper.
    if "scores" in obj and isinstance(obj["scores"], dict):
        obj = obj["scores"]

    missing = [a for a in AXES if a not in obj]
    if missing:
        raise ValueError(f"scores response missing axes: {missing}")

    return {axis: _validate_axis(axis, obj[axis]) for axis in AXES}


def _validate_axis(axis: str, entry: object) -> dict:
    """Validate one axis entry into ``{score, evidence, reason:{en,nl}}``.

    The score<->evidence invariant is enforced by *normalization, not rejection*:
    models routinely pair a numeric score with ``no_signal`` (or a null score with a
    numeric evidence level), and discarding the whole company over that throws away
    otherwise-good axes. So a numeric score with ``no_signal`` keeps its score and is
    downgraded to ``partial``; a null score with a numeric level is forced to
    ``no_signal``. Only genuinely unusable output (bad evidence value, non-integer
    non-null score, missing reason) is a hard error.
    """
    if not isinstance(entry, dict):
        raise ValueError(f"axis {axis!r} is not an object")

    evidence = entry.get("evidence")
    if evidence not in EVIDENCE_LEVELS:
        raise ValueError(f"axis {axis!r} has invalid evidence {evidence!r}")

    score = entry.get("score")
    if score is not None:
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError(f"axis {axis!r} score must be an integer 0-100 or null, got {score!r}")
        if not 0 <= score <= 100:
            raise ValueError(f"axis {axis!r} score {score} out of range 0-100")

    # Normalize the score<->evidence pairing rather than rejecting it.
    if score is not None and evidence == "no_signal":
        evidence = "partial"
    elif score is None and evidence != "no_signal":
        evidence = "no_signal"

    reason = entry.get("reason")
    if not isinstance(reason, dict):
        raise ValueError(f"axis {axis!r} reason is not an object")
    en = reason.get("en")
    if not isinstance(en, str) or not en.strip():
        raise ValueError(f"axis {axis!r} reason missing non-empty 'en'")

    return {"score": score, "evidence": evidence, "reason": {"en": en.strip()}}
