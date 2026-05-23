"""Per-company axis scorer and batch runner for global-scoring."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.website_resolution import company_id

from . import frontmatter
from . import llm as llm_module

DEFAULT_CONTENT_DIR = Path("data/content-summarization")

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "global-scoring.md"


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
    """Score one company on the five axes. Raises only on company-id collision."""
    if meta.get("status") != "ok":
        result = _record(meta, status="upstream_failed")
    elif not body.strip():
        result = _record(meta, status="empty")
    elif offline:
        result = _record(meta, status="empty")
    else:
        try:
            scores = llm_module.call(build_messages(body))
            result = _record(
                meta,
                status="ok",
                scores=scores,
                model=llm_module.resolve_model(),
            )
        except llm_module.LLMError:
            result = _record(meta, status="llm_error")

    if write:
        _write(result, out_dir=out_dir)
    return result


def run(
    records: Iterable[dict],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    content_dir: Path | None = None,
) -> Iterator[dict]:
    """Yield one score record per company. Never raises on per-company load errors."""
    src = content_dir if content_dir is not None else DEFAULT_CONTENT_DIR
    for record in records:
        try:
            meta, body = _load_company(record, content_dir=src)
            yield process(meta, body, out_dir=out_dir, write=write, offline=offline)
        except Exception as exc:
            failed = _record(record, status="upstream_failed")
            failed["_error"] = str(exc)
            yield failed


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
    """Load the global-scoring prompt from the versioned file under ``prompts/``."""
    return PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Record construction and I/O
# ---------------------------------------------------------------------------


def _record(
    meta: dict,
    *,
    status: str,
    scores: dict | None = None,
    model: str | None = None,
) -> dict:
    return {
        "name": meta.get("name"),
        "website": meta.get("website"),
        "status": status,
        "model": model,
        "scores": scores,
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
