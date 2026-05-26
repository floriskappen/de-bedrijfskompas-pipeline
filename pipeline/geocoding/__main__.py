"""CLI entry point: ``python -m pipeline.geocoding``."""

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
    pass

from .core import run

DEFAULT_INPUT = Path("data/fact-extraction")
DEFAULT_OUT_DIR = Path("data/geocoding")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.geocoding",
        description="Geocode company addresses using PDOK.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Directory of fact-extraction output (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write geocoded JSON (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit records as JSON Lines to stdout.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip all HTTP calls (companies needing lookup get status=empty).",
    )
    parser.add_argument(
        "--company",
        metavar="ID",
        help="Process only the company with this id (file stem under --input).",
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
    ):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))
        status = str(result.get("status", "unknown"))
        status_counts[status] += 1
        latlng = result.get("latlng") or {}
        lat = latlng.get("lat")
        lng = latlng.get("lng")
        latlng_str = f"{lat},{lng}" if lat is not None else "None"
        print(
            f"{result.get('name', '?')}: status={status} "
            f"latlng={latlng_str} match_quality={result.get('match_quality')}",
            file=sys.stderr,
        )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0

def _discover_records(input_dir: Path, *, company_filter: str | None) -> list[dict]:
    if not input_dir.exists():
        raise SystemExit(f"input directory not found: {input_dir}")

    records: list[dict] = []
    for path in sorted(input_dir.iterdir()):
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        if company_filter and path.stem != company_filter:
            continue
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records

if __name__ == "__main__":
    raise SystemExit(main())
