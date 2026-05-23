"""CLI entry point: ``python -m pipeline.dataset_output``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .core import DEFAULT_OUT_DIR, FACT_DIR, run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.dataset_output",
        description="Project per-stage outputs into one frontend-facing record per company.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=FACT_DIR,
        help=f"fact-extraction directory used as the enumeration spine (default: {FACT_DIR}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company dataset records (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit records as JSON Lines to stdout.",
    )
    parser.add_argument(
        "--company",
        metavar="ID",
        help="Process only the company with this id (fact-extraction filename stem).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N companies.",
    )
    args = parser.parse_args(argv)

    company_ids = _discover(args.input, company_filter=args.company)
    if args.limit is not None:
        company_ids = company_ids[: args.limit]

    status_counts: Counter[str] = Counter()
    for result in run(
        company_ids,
        out_dir=args.out_dir,
        write=not args.dry_run,
        fact_dir=args.input,
    ):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))
        status = str(result.get("status", "unknown"))
        status_counts[status] += 1
        print(f"{result.get('name') or result.get('company_id', '?')}: status={status}", file=sys.stderr)

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0


def _discover(input_dir: Path, *, company_filter: str | None) -> list[str]:
    """Enumerate company ids from the fact-extraction spine (single-file layout)."""
    if not input_dir.exists():
        raise SystemExit(f"input directory not found: {input_dir}")

    company_ids: list[str] = []
    for path in sorted(input_dir.glob("*.json")):
        if company_filter and path.stem != company_filter:
            continue
        company_ids.append(path.stem)
    return company_ids


if __name__ == "__main__":
    raise SystemExit(main())
