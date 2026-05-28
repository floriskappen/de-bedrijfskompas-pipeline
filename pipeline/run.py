"""End-to-end pipeline orchestrator.

Drives every stage in the declared dependency order, sequentially, in-process.
Each stage's ``run()`` is called directly — never via subprocess. With
``--resume``, the orchestrator skips ``(stage, company)`` pairs whose output
already exists on disk; without ``--resume``, every stage is invoked for
every company and each stage's own overwrite semantics apply.

CLI: ``python -m pipeline.run --input <seed.json> [--resume] [--publish]``.

See openspec/specs/pipeline-architecture/spec.md for the full contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # python-dotenv is optional; env can be pre-exported
    pass

DATA_ROOT = Path("data")


# ---------------------------------------------------------------------------
# Existence helpers (the per-stage layout knowledge lives here, in one place)
# ---------------------------------------------------------------------------


def _exists_single(stage_dir: Path, cid: str) -> bool:
    """Single-file layout: ``data/<stage>/<id>.json``."""
    return (stage_dir / f"{cid}.json").exists()


def _exists_subdir(stage_dir: Path, cid: str) -> bool:
    """Subdirectory layout: ``data/<stage>/<id>/_meta.json``."""
    return (stage_dir / cid / "_meta.json").exists()


def _exists_dossier(stage_dir: Path, cid: str) -> bool:
    """Dossier layout: ``data/<stage>/<id>.md`` (content-summarization)."""
    return (stage_dir / f"{cid}.md").exists()


# ---------------------------------------------------------------------------
# Per-stage drivers
# ---------------------------------------------------------------------------
# Each driver is responsible for: (a) discovering its inputs from the upstream
# stage's directory (or from the seed list for website-resolution), (b)
# filtering out companies whose output already exists when ``resume`` is set,
# and (c) calling its stage's ``run()`` entry point in-process.


def _drive_website_resolution(seed: list[dict], *, resume: bool, data_root: Path) -> None:
    from pipeline.website_resolution.core import company_id, run

    out_dir = data_root / "website-resolution"
    out_dir.mkdir(parents=True, exist_ok=True)
    if resume:
        records = [
            r
            for r in seed
            if isinstance(r.get("name"), str)
            and r["name"].strip()
            and not _exists_single(out_dir, company_id(r["name"]))
        ]
    else:
        records = list(seed)
    list(run(records, write=True, out_dir=out_dir))


def _drive_content_collection(*, resume: bool, data_root: Path) -> None:
    from pipeline.content_collection.core import run

    in_dir = data_root / "website-resolution"
    out_dir = data_root / "content-collection"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_single_file_records(in_dir, out_dir, resume=resume, exists=_exists_subdir)
    list(run(records, write=True, out_dir=out_dir))


def _drive_fact_extraction(*, resume: bool, data_root: Path) -> None:
    from pipeline.fact_extraction.core import run

    content_dir = data_root / "content-collection"
    out_dir = data_root / "fact-extraction"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_meta_records(content_dir, out_dir, resume=resume)
    list(run(records, write=True, out_dir=out_dir, content_dir=content_dir))


def _drive_content_summarization(*, resume: bool, data_root: Path) -> None:
    from pipeline.content_summarization.core import run

    content_dir = data_root / "content-collection"
    out_dir = data_root / "content-summarization"
    out_dir.mkdir(parents=True, exist_ok=True)
    # content-summarization writes <id>.md dossiers, not <id>.json — its
    # existence check uses the .md suffix.
    records: list[dict] = []
    if content_dir.exists():
        for sub in sorted(content_dir.iterdir()):
            meta = sub / "_meta.json"
            if not meta.exists():
                continue
            cid = sub.name
            if resume and _exists_dossier(out_dir, cid):
                continue
            try:
                records.append(json.loads(meta.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
    list(run(records, write=True, out_dir=out_dir, content_dir=content_dir))


def _drive_geocoding(*, resume: bool, data_root: Path) -> None:
    from pipeline.geocoding.core import run

    in_dir = data_root / "fact-extraction"
    out_dir = data_root / "geocoding"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_single_file_records(in_dir, out_dir, resume=resume, exists=_exists_single)
    list(run(records, write=True, out_dir=out_dir))


def _drive_tagline_extraction(*, resume: bool, data_root: Path) -> None:
    from pipeline.tagline_extraction.core import run

    content_dir = data_root / "content-summarization"
    out_dir = data_root / "tagline-extraction"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_dossier_records(content_dir, out_dir, resume=resume)
    list(run(records, write=True, out_dir=out_dir, content_dir=content_dir))


def _drive_global_scoring(*, resume: bool, data_root: Path) -> None:
    from pipeline.global_scoring.core import run

    content_dir = data_root / "content-summarization"
    out_dir = data_root / "global-scoring"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_dossier_records(content_dir, out_dir, resume=resume)
    list(run(records, write=True, out_dir=out_dir, content_dir=content_dir))


def _drive_tagging(*, resume: bool, data_root: Path) -> None:
    from pipeline.tagging.core import run

    content_dir = data_root / "content-summarization"
    out_dir = data_root / "tagging"
    out_dir.mkdir(parents=True, exist_ok=True)
    records = _load_dossier_records(content_dir, out_dir, resume=resume)
    list(run(records, write=True, out_dir=out_dir, content_dir=content_dir))


def _drive_translation(*, resume: bool, data_root: Path) -> None:
    from pipeline.translation.core import run
    from pipeline.translation.llm import TRANSLATION_TARGETS

    out_dir = data_root / "translation"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Source dirs are derived from data_root so --data-root is honoured end-to-end.
    source_dirs: dict[str, Path] = {
        "tagline-extraction": data_root / "tagline-extraction",
        "global-scoring": data_root / "global-scoring",
    }

    name_by_id: dict[str, str] = {}
    website_by_id: dict[str, str | None] = {}
    for stage_id, _ in TRANSLATION_TARGETS:
        src_dir = source_dirs.get(stage_id)
        if src_dir is None or not src_dir.exists():
            continue
        for record_path in sorted(src_dir.glob("*.json")):
            stem = record_path.stem
            if resume and _exists_single(out_dir, stem):
                continue
            try:
                rec = json.loads(record_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            name = rec.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            if stem not in name_by_id:
                name_by_id[stem] = name
                website_by_id[stem] = rec.get("website")

    companies = [(name_by_id[stem], website_by_id[stem]) for stem in sorted(name_by_id)]
    list(run(companies, write=True, out_dir=out_dir, source_dirs=source_dirs))


def _drive_dataset_output(*, resume: bool, data_root: Path) -> None:
    from pipeline.dataset_output.core import run

    fact_dir = data_root / "fact-extraction"
    out_dir = data_root / "dataset-output"
    out_dir.mkdir(parents=True, exist_ok=True)
    # dataset-output writes a single aggregate companies.json — there is no
    # per-company on-disk record to skip on. resume has no effect here; we
    # always rebuild the aggregate over the current fact-extraction spine.
    company_ids = [p.stem for p in sorted(fact_dir.glob("*.json"))] if fact_dir.exists() else []
    list(
        run(
            company_ids,
            write=True,
            out_dir=out_dir,
            fact_dir=fact_dir,
            scoring_dir=data_root / "global-scoring",
            tagline_dir=data_root / "tagline-extraction",
            tagging_dir=data_root / "tagging",
            translation_dir=data_root / "translation",
            geocoding_dir=data_root / "geocoding",
        )
    )


# ---------------------------------------------------------------------------
# Discovery helpers shared by the simpler stage drivers
# ---------------------------------------------------------------------------


def _load_single_file_records(
    in_dir: Path, out_dir: Path, *, resume: bool, exists: Callable[[Path, str], bool]
) -> list[dict]:
    """Read each ``*.json`` under ``in_dir`` as a record; drop those already done."""
    records: list[dict] = []
    if not in_dir.exists():
        return records
    for path in sorted(in_dir.glob("*.json")):
        cid = path.stem
        if resume and exists(out_dir, cid):
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


def _load_dossier_records(content_dir: Path, out_dir: Path, *, resume: bool) -> list[dict]:
    """Discover content-summarization dossiers (``*.md``) and seed records from frontmatter.

    Mirrors the per-stage ``_discover_records`` helper used by tagline-extraction
    and global-scoring: each dossier's frontmatter ``name`` / ``website`` form the
    record; ``core`` re-reads the file for the authoritative body.
    """
    from pipeline.tagline_extraction import frontmatter

    records: list[dict] = []
    if not content_dir.exists():
        return records
    for dossier in sorted(content_dir.glob("*.md")):
        cid = dossier.stem
        if resume and _exists_single(out_dir, cid):
            continue
        try:
            fields, _body = frontmatter.parse(dossier.read_text(encoding="utf-8"))
        except OSError:
            continue
        name = fields.get("name")
        if not name:
            continue
        records.append({"name": name, "website": fields.get("website")})
    return records


def _load_meta_records(content_dir: Path, out_dir: Path, *, resume: bool) -> list[dict]:
    """Discover content-collection subdirectories and load each ``_meta.json``."""
    records: list[dict] = []
    if not content_dir.exists():
        return records
    for sub in sorted(content_dir.iterdir()):
        meta = sub / "_meta.json"
        if not meta.exists():
            continue
        cid = sub.name
        if resume and _exists_single(out_dir, cid):
            continue
        try:
            records.append(json.loads(meta.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return records


# ---------------------------------------------------------------------------
# Stage table (declaration order matches pipeline-architecture)
# ---------------------------------------------------------------------------


# Each entry: (stage-name, driver-callable). The driver signature is
# ``(seed, *, resume, data_root)`` — most drivers ignore ``seed``; only
# website-resolution uses it.
StageDriver = Callable[..., None]

STAGES: list[tuple[str, StageDriver]] = [
    ("website-resolution", lambda seed, *, resume, data_root: _drive_website_resolution(seed, resume=resume, data_root=data_root)),
    ("content-collection", lambda seed, *, resume, data_root: _drive_content_collection(resume=resume, data_root=data_root)),
    ("fact-extraction", lambda seed, *, resume, data_root: _drive_fact_extraction(resume=resume, data_root=data_root)),
    ("content-summarization", lambda seed, *, resume, data_root: _drive_content_summarization(resume=resume, data_root=data_root)),
    ("geocoding", lambda seed, *, resume, data_root: _drive_geocoding(resume=resume, data_root=data_root)),
    ("tagline-extraction", lambda seed, *, resume, data_root: _drive_tagline_extraction(resume=resume, data_root=data_root)),
    ("global-scoring", lambda seed, *, resume, data_root: _drive_global_scoring(resume=resume, data_root=data_root)),
    ("tagging", lambda seed, *, resume, data_root: _drive_tagging(resume=resume, data_root=data_root)),
    ("translation", lambda seed, *, resume, data_root: _drive_translation(resume=resume, data_root=data_root)),
    ("dataset-output", lambda seed, *, resume, data_root: _drive_dataset_output(resume=resume, data_root=data_root)),
]


def run_pipeline(
    seed: list[dict], *, resume: bool, publish: bool, data_root: Path = DATA_ROOT
) -> int:
    """Drive every stage to completion, optionally invoking publish on success.

    Returns 0 on success, 1 if publish was requested and failed (the pipeline
    work is still on disk for a standalone retry).
    """

    for name, driver in STAGES:
        print(f"=== {name} ===", file=sys.stderr)
        driver(seed, resume=resume, data_root=data_root)

    if publish:
        from pipeline.publish.core import PublishError
        from pipeline.publish.core import publish as run_publish

        try:
            run_publish(data_path=data_root / "dataset-output" / "companies.json")
        except PublishError as exc:
            print(f"publish failed: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001 — surface anything else loudly
            print(f"publish failed: {exc}", file=sys.stderr)
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.run",
        description="Drive every pipeline stage in order over a JSON input list.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the seed JSON array (same shape as website-resolution's --input).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip (stage, company) pairs whose stage output already exists on disk.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="After dataset-output succeeds, invoke pipeline.publish to upload.",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=DATA_ROOT,
        help=f"Root directory for per-stage outputs (default: {DATA_ROOT}).",
    )
    args = parser.parse_args(argv)

    try:
        seed = json.loads(args.input.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"failed to read --input {args.input}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(seed, list):
        print(f"--input must be a JSON array, got {type(seed).__name__}", file=sys.stderr)
        return 2

    return run_pipeline(
        seed, resume=args.resume, publish=args.publish, data_root=args.data_root
    )


if __name__ == "__main__":
    raise SystemExit(main())
