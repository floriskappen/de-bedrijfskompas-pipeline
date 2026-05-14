"""CLI entry point: ``python -m pipeline.fact_extraction``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass  # python-dotenv optional; key can be pre-exported

from .core import run

DEFAULT_INPUT = Path("data/content-collection")
DEFAULT_OUT_DIR = Path("data/fact-extraction")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.fact_extraction",
        description="Extract structured facts (HQ address) from content-collection output.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Directory of content-collection output (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company JSON (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit records as JSON Lines to stdout.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all LLM calls (regex-only; companies needing LLM get status=empty).",
    )
    parser.add_argument(
        "--company",
        metavar="ID",
        help="Process only the company with this id (directory name under --input).",
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
        addr = result.get("address") or {}
        print(
            f"{result.get('name', '?')}: status={status} "
            f"postcode={addr.get('postcode')} city={addr.get('city')}",
            file=sys.stderr,
        )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0


def _discover_records(input_dir: Path, *, company_filter: str | None) -> list[dict]:
    if not input_dir.exists():
        raise SystemExit(f"input directory not found: {input_dir}")

    records: list[dict] = []
    for company_dir in sorted(input_dir.iterdir()):
        if not company_dir.is_dir():
            continue
        if company_filter and company_dir.name != company_filter:
            continue
        meta_path = company_dir / "_meta.json"
        if not meta_path.exists():
            continue
        records.append(json.loads(meta_path.read_text(encoding="utf-8")))
    return records


if __name__ == "__main__":
    raise SystemExit(main())
