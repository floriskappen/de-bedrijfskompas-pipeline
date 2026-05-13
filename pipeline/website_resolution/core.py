"""Per-record resolver and batch runner for the website-resolution stage."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from slugify import slugify

from . import search as _search

SLEEP_BETWEEN_SEARCHES_SECONDS = 1.5

# Entity suffixes trimmed from the end of a company name before slugification.
# Match `B.V.`, `B.V`, `BV`, `N.V.`, `N.V`, `NV`, `Holding`, `Holdings`
# case-insensitively, with surrounding whitespace.
_ENTITY_SUFFIX_RE = re.compile(
    r"\s+(B\.?V\.?|N\.?V\.?|Holdings?)\s*$",
    re.IGNORECASE,
)


def company_id(name: str) -> str:
    """Derive the canonical `<company-id>` for a company name.

    See module docstring for the rule. Slugification is via
    `python-slugify`; entity suffixes are stripped first so
    "Land Life Company B.V." and "Land Life Company" both collapse to
    `land-life-company`.

    Changing this rule is a **breaking change** for all stored data.
    """

    if not name or not name.strip():
        raise ValueError("company_id requires a non-empty name")

    trimmed = _ENTITY_SUFFIX_RE.sub("", name).strip()
    return slugify(trimmed or name)


def resolve(record: dict) -> dict:
    """Resolve a single input record into an output record.

    Behavior follows the `website-resolution` spec:
    - Missing/empty `name` → failure record.
    - `website` already present → record returned unchanged.
    - Otherwise → DDGS search, success on a hit, failure on no hits or
      a search-backend exception.
    """

    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        return _fail(record, "missing or empty name")

    website = record.get("website")
    if isinstance(website, str) and website.strip():
        return dict(record)

    try:
        url = _search.search(name)
    except Exception as exc:
        return _fail(record, f"search backend error: {exc}")

    if url is None:
        return _fail(record, "no search results")

    out = dict(record)
    out["website"] = url
    return out


def run(
    records: Iterable[dict],
    *,
    write: bool,
    out_dir: Path,
) -> Iterator[dict]:
    """Process a batch of records.

    Yields each resolved record. When `write=True`, also persists each
    record to `<out_dir>/<company-id>.json` and refuses to silently
    overwrite a file produced by a different company.

    Sleeps `SLEEP_BETWEEN_SEARCHES_SECONDS` between consecutive
    search-triggering records (records with an existing `website` do not
    incur a sleep).
    """

    searched_once = False

    for record in records:
        if _needs_search(record):
            if searched_once:
                time.sleep(SLEEP_BETWEEN_SEARCHES_SECONDS)
            searched_once = True

        result = resolve(record)

        if write:
            _persist(result, out_dir)

        yield result


def _needs_search(record: dict) -> bool:
    name = record.get("name")
    website = record.get("website")
    name_ok = isinstance(name, str) and bool(name.strip())
    website_present = isinstance(website, str) and bool(website.strip())
    return name_ok and not website_present


def _fail(record: dict, error: str) -> dict:
    out = dict(record)
    out["website"] = None
    out["status"] = "failed"
    out["error"] = error
    return out


def _persist(record: dict, out_dir: Path) -> None:
    name = record.get("name")
    if not isinstance(name, str) or not name.strip():
        # Invalid records are still emitted but we cannot derive a stable
        # filename for them; skip the write rather than guess.
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{company_id(name)}.json"

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing_name = existing.get("name")
        except (OSError, json.JSONDecodeError):
            existing_name = None

        if isinstance(existing_name, str) and existing_name != name:
            raise RuntimeError(
                f"company-id collision at {path}: "
                f"existing record has name={existing_name!r}, "
                f"new record has name={name!r}"
            )

    path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
