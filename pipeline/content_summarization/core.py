"""Per-company dossier generator and batch runner for content-summarization."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.website_resolution import company_id

from . import llm as llm_module

INPUT_CHAR_LIMIT = 24000  # cap on the concatenated page text fed to the LLM

DEFAULT_CONTENT_DIR = Path("data/content-collection")
DEFAULT_CONCURRENCY = 8

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "content-summarization.md"

# Common Dutch function words — used to distinguish nl from en source text.
_DUTCH_WORDS = frozenset(
    {
        "de", "het", "een", "en", "van", "voor", "met", "zijn", "wordt", "worden",
        "onze", "wij", "ons", "niet", "ook", "aan", "bij", "naar", "over", "door",
        "maar", "heeft", "hebben", "dat", "die", "deze", "u", "je", "om", "te",
    }
)
_WORD_RE = re.compile(r"[a-zà-ÿ]+", re.IGNORECASE)

_FRONTMATTER_KEYS = ("name", "website", "status", "source_language", "model")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def process(
    meta: dict,
    pages: dict[str, str],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
) -> dict:
    """Summarise a single company. Raises only on company-id collision (in _write)."""
    upstream_status = meta.get("status", "")
    if upstream_status in ("upstream_failed", "fetch_failed"):
        result = _record(meta, status="upstream_failed", body="", source_language=None)
    else:
        surface = build_input(pages)
        if not surface.strip():
            result = _record(meta, status="empty", body="", source_language=None)
        elif offline:
            result = _record(meta, status="empty", body="", source_language=None)
        else:
            source_language = detect_language(surface)
            try:
                raw = llm_module.call(build_messages(surface))
                body = llm_module.strip_wrapper(raw)
                result = _record(
                    meta,
                    status="ok",
                    body=body,
                    source_language=source_language,
                    model=llm_module.resolve_model(),
                )
            except llm_module.LLMError:
                result = _record(meta, status="llm_error", body="", source_language=source_language)

    if write:
        _write(result, out_dir=out_dir)
    return result


def _resolve_concurrency() -> int:
    """Bound the per-stage LLM pool: ``CONTENT_SUMMARIZATION_CONCURRENCY`` env, default 8."""
    raw = os.environ.get("CONTENT_SUMMARIZATION_CONCURRENCY")
    if raw is None:
        return DEFAULT_CONCURRENCY
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_CONCURRENCY
    return max(1, n)


def run(
    records: Iterable[dict],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    content_dir: Path | None = None,
) -> Iterator[dict]:
    """Yield one dossier record per company, in input order. Never raises on per-company load errors.

    Companies are processed concurrently in a bounded pool
    (``CONTENT_SUMMARIZATION_CONCURRENCY``); results are reassembled and yielded
    in input order. Per-company failures are isolated as records rather than
    aborting the batch.
    """
    src = content_dir if content_dir is not None else DEFAULT_CONTENT_DIR
    record_list = list(records)

    def _one(record: dict) -> dict:
        try:
            meta, pages = _load_company(record, content_dir=src)
            return process(meta, pages, out_dir=out_dir, write=write, offline=offline)
        except Exception as exc:
            failed = _record(record, status="upstream_failed", body="", source_language=None)
            failed["_error"] = str(exc)
            return failed

    concurrency = _resolve_concurrency()
    if concurrency <= 1 or len(record_list) <= 1:
        for record in record_list:
            yield _one(record)
        return

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for result in ex.map(_one, record_list):
            yield result


# ---------------------------------------------------------------------------
# Input assembly (pure functions)
# ---------------------------------------------------------------------------


def build_input(pages: dict[str, str]) -> str:
    """Concatenate precision page bodies: index first, then slugs alphabetically.

    Each body is prefixed with its slug; the result is truncated to INPUT_CHAR_LIMIT.
    """
    if not pages:
        return ""
    ordered = (["index"] if "index" in pages else []) + sorted(s for s in pages if s != "index")
    parts = [f"## [{slug}]\n{pages[slug]}" for slug in ordered]
    return "\n\n".join(parts)[:INPUT_CHAR_LIMIT]


def build_messages(surface: str) -> list[dict]:
    """Build the chat messages: versioned prompt as system, page text as user."""
    return [
        {"role": "system", "content": load_prompt()},
        {"role": "user", "content": f"Company website content:\n\n{surface}"},
    ]


def load_prompt() -> str:
    """Load the dossier prompt from the versioned file under ``prompts/``."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def detect_language(text: str) -> str | None:
    """Return ``"nl"`` or ``"en"`` for the dominant source language, or None if empty."""
    words = _WORD_RE.findall(text.lower())
    if not words:
        return None
    sample = words[:400]
    dutch_ratio = sum(1 for w in sample if w in _DUTCH_WORDS) / len(sample)
    return "nl" if dutch_ratio > 0.06 else "en"


# ---------------------------------------------------------------------------
# Record construction and I/O
# ---------------------------------------------------------------------------


def _record(
    meta: dict,
    *,
    status: str,
    body: str,
    source_language: str | None,
    model: str | None = None,
) -> dict:
    return {
        "name": meta.get("name"),
        "website": meta.get("website"),
        "status": status,
        "source_language": source_language,
        "model": model,
        "body": body,
    }


def _load_company(record: dict, *, content_dir: Path) -> tuple[dict, dict[str, str]]:
    """Load _meta.json and precision page markdown (excluding *.recall.md)."""
    name = record.get("name", "")
    company_dir = content_dir / company_id(name)

    meta_path = company_dir / "_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    else:
        meta = dict(record)
        meta["status"] = "upstream_failed"

    pages: dict[str, str] = {}
    for md in sorted(company_dir.glob("*.md")):
        if md.name.endswith(".recall.md"):
            continue
        pages[md.name[:-3]] = md.read_text(encoding="utf-8")

    return meta, pages


def _write(result: dict, *, out_dir: Path) -> None:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{company_id(name)}.md"

    if out_path.exists():
        existing_name = _read_frontmatter_name(out_path)
        if existing_name is not None and existing_name != name:
            raise RuntimeError(
                f"company-id collision at {out_path}: "
                f"existing name={existing_name!r}, new name={name!r}"
            )

    out_path.write_text(_render(result), encoding="utf-8")


def _render(result: dict) -> str:
    lines = ["---"]
    for key in _FRONTMATTER_KEYS:
        lines.append(f"{key}: {_yaml_scalar(result.get(key))}")
    lines.append("---")
    body = result.get("body") or ""
    out = "\n".join(lines) + "\n\n" + body
    return out if out.endswith("\n") else out + "\n"


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _read_frontmatter_name(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            return _unquote(line[len("name:"):].strip())
    return None


def _unquote(s: str) -> str | None:
    if s == "null":
        return None
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s
