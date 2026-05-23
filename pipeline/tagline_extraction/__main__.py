"""CLI entry point: ``python -m pipeline.tagline_extraction``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass  # python-dotenv optional; key can be pre-exported

from .core import run

DEFAULT_INPUT = Path("data/content-summarization")
DEFAULT_OUT_DIR = Path("data/tagline-extraction")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.tagline_extraction",
        description="Generate an English plain-language tagline per company from its dossier.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Directory of content-summarization dossiers (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company tagline records (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit records as JSON Lines to stdout.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all LLM calls (companies needing one get status=empty).",
    )
    parser.add_argument(
        "--company",
        metavar="ID",
        help="Process only the company with this id (dossier filename stem under --input).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N companies.",
    )
    args = parser.parse_args(argv)

    records = _discover_records(args.input, company_filter=args.company)
    if args.limit is not None:
        records = records[: args.limit]

    status_counts: Counter[str] = Counter()
    for result in run(
        records,
        out_dir=args.out_dir,
        write=not args.dry_run,
        offline=args.offline,
        content_dir=args.input,
    ):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))
        status = str(result.get("status", "unknown"))
        status_counts[status] += 1
        tagline = result.get("tagline") or {}
        print(
            f"{result.get('name', '?')}: status={status} "
            f"en={tagline.get('en')!r}",
            file=sys.stderr,
        )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0


def _discover_records(input_dir: Path, *, company_filter: str | None) -> list[dict]:
    """Discover companies from the dossier ``.md`` files (single-file layout).

    Each dossier's frontmatter ``name``/``website`` seed the record; ``core`` re-reads
    the file for the authoritative frontmatter and body.
    """
    if not input_dir.exists():
        raise SystemExit(f"input directory not found: {input_dir}")

    from . import frontmatter

    records: list[dict] = []
    for dossier in sorted(input_dir.glob("*.md")):
        if company_filter and dossier.stem != company_filter:
            continue
        fields, _ = frontmatter.parse(dossier.read_text(encoding="utf-8"))
        name = fields.get("name")
        if not name:
            continue
        records.append({"name": name, "website": fields.get("website")})
    return records


if __name__ == "__main__":
    raise SystemExit(main())
