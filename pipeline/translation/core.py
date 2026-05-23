"""Fan-in translation stage: reads analytic-stage outputs and produces nl strings."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from pipeline.website_resolution import company_id

from . import llm as llm_module
from .llm import TRANSLATION_TARGETS

DEFAULT_SOURCE_DIRS: dict[str, Path] = {
    "tagline-extraction": Path("data/tagline-extraction"),
    "global-scoring": Path("data/global-scoring"),
}


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def process(
    name: str,
    website: str | None,
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    source_dirs: dict[str, Path] | None = None,
) -> dict:
    """Translate all registered targets for one company. Raises only on collision."""
    src = source_dirs if source_dirs is not None else DEFAULT_SOURCE_DIRS
    targets = _collect_targets(name, src)

    if not targets:
        result = _record(name, website, status="upstream_failed")
    elif offline:
        result = _record(name, website, status="empty")
    else:
        try:
            messages = llm_module.build_messages(targets)
            nl_map = llm_module.call(messages, expected_keys=set(targets))
            translations = {k: {"nl": v} for k, v in nl_map.items()}
            result = _record(
                name,
                website,
                status="ok",
                translations=translations,
                model=llm_module.resolve_model(),
            )
        except llm_module.LLMError:
            result = _record(name, website, status="llm_error")

    if write:
        _write(result, out_dir=out_dir)
    return result


def run(
    companies: Iterable[tuple[str, str | None]],
    *,
    out_dir: Path,
    write: bool,
    offline: bool = False,
    source_dirs: dict[str, Path] | None = None,
) -> Iterator[dict]:
    """Yield one translation record per company. Never raises on per-company errors."""
    for name, website in companies:
        try:
            yield process(name, website, out_dir=out_dir, write=write, offline=offline, source_dirs=source_dirs)
        except Exception as exc:
            failed = _record(name, website, status="upstream_failed")
            failed["_error"] = str(exc)
            yield failed


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def _collect_targets(name: str, source_dirs: dict[str, Path]) -> dict[str, str]:
    """Read each source-stage output and extract registered en strings.

    Returns a flat dict of {resolved_path_key: en_text}. Sources that are
    missing or non-ok contribute nothing (silently skipped).
    """
    cid = company_id(name)
    collected: dict[str, str] = {}

    for stage_id, path_expr in TRANSLATION_TARGETS:
        src_dir = source_dirs.get(stage_id)
        if src_dir is None:
            continue
        record_path = src_dir / f"{cid}.json"
        if not record_path.exists():
            continue
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if record.get("status") != "ok":
            continue
        resolved = llm_module.resolve_targets(record, path_expr)
        # Prefix keys with the stage-relative path only — the path_expr already
        # encodes the field structure, so the flat key is just the resolved path.
        collected.update(resolved)

    return collected


# ---------------------------------------------------------------------------
# Record construction and I/O
# ---------------------------------------------------------------------------


def _record(
    name: str,
    website: str | None,
    *,
    status: str,
    translations: dict | None = None,
    model: str | None = None,
) -> dict:
    return {
        "name": name,
        "website": website,
        "status": status,
        "model": model,
        "translations": translations,
    }


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
