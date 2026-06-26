"""Per-company tagline generator and batch runner for tagline-extraction."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline.website_resolution import company_id

from . import frontmatter
from . import llm as llm_module

DEFAULT_CONTENT_DIR = Path("data/content-summarization")
DEFAULT_CONCURRENCY = 8

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "tagline-extraction.md"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def process(
    meta: dict,
    body: str,
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
) -> dict:
    """Generate an English tagline for one company. Raises only on company-id collision."""
    if meta.get("status") != "ok":
        result = _record(meta, status="upstream_failed")
    elif not body.strip():
        result = _record(meta, status="empty")
    elif offline:
        result = _record(meta, status="empty")
    else:
        try:
            tagline = llm_module.call(build_messages(body))
            result = _record(
                meta,
                status="ok",
                tagline=tagline,
                model=llm_module.resolve_model(),
            )
        except llm_module.LLMError:
            result = _record(meta, status="llm_error")

    if write:
        _write(result, out_dir=out_dir)
    return result


def _resolve_concurrency() -> int:
    """Bound the per-stage LLM pool: ``TAGLINE_EXTRACTION_CONCURRENCY`` env, default 8."""
    raw = os.environ.get("TAGLINE_EXTRACTION_CONCURRENCY")
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
    """Yield one tagline record per company, in input order. Never raises on per-company load errors.

    Companies are processed concurrently in a bounded pool (``TAGLINE_EXTRACTION_CONCURRENCY``);
    results are reassembled and yielded in input order. Per-company failures are
    isolated as records rather than aborting the batch.
    """
    src = content_dir if content_dir is not None else DEFAULT_CONTENT_DIR
    record_list = list(records)

    def _one(record: dict) -> dict:
        try:
            meta, body = _load_company(record, content_dir=src)
            return process(meta, body, out_dir=out_dir, write=write, offline=offline)
        except Exception as exc:
            failed = _record(record, status="upstream_failed")
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
# Prompt / message assembly
# ---------------------------------------------------------------------------


def build_messages(body: str) -> list[dict]:
    """Build the chat messages: versioned prompt as system, dossier body as user."""
    return [
        {"role": "system", "content": load_prompt()},
        {"role": "user", "content": f"Company dossier:\n\n{body}"},
    ]


def load_prompt() -> str:
    """Load the tagline prompt from the versioned file under ``prompts/``."""
    return PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Record construction and I/O
# ---------------------------------------------------------------------------


def _record(
    meta: dict,
    *,
    status: str,
    tagline: dict | None = None,
    model: str | None = None,
) -> dict:
    return {
        "name": meta.get("name"),
        "website": meta.get("website"),
        "status": status,
        "model": model,
        "tagline": tagline if tagline is not None else {"en": None},
    }


def _load_company(record: dict, *, content_dir: Path) -> tuple[dict, str]:
    """Load a company's dossier frontmatter and body.

    A missing dossier is reported as ``status: upstream_failed`` with an empty body
    rather than an error, so the company still gets a record.
    """
    name = record.get("name", "")
    dossier_path = content_dir / f"{company_id(name)}.md"

    if not dossier_path.exists():
        meta = {
            "name": record.get("name"),
            "website": record.get("website"),
            "status": "upstream_failed",
        }
        return meta, ""

    fields, body = frontmatter.parse(dossier_path.read_text(encoding="utf-8"))
    meta = {
        "name": fields.get("name") or record.get("name"),
        "website": fields.get("website") or record.get("website"),
        "status": fields.get("status"),
    }
    return meta, body


def _write(result: dict, *, out_dir: Path) -> None:
    name = result.get("name")
    if not isinstance(name, str) or not name.strip():
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{company_id(name)}.json"

    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("name") != name:
            raise RuntimeError(
                f"company-id collision at {out_path}: "
                f"existing name={existing.get('name')!r}, new name={name!r}"
            )

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
