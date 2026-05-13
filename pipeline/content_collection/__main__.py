"""CLI entry point: ``python -m pipeline.content_collection``."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .core import DEFAULT_INTER_PAGE_SLEEP, run

DEFAULT_INPUT = Path("data/website-resolution")
DEFAULT_OUT_DIR = Path("data/content-collection")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.content_collection",
        description=(
            "Fetch each company's homepage and a curated set of internal "
            "pages, extract markdown via trafilatura, and persist results."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=(
            f"Path to a directory of upstream JSON records, or a single "
            f"JSON file (default: {DEFAULT_INPUT})."
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company output (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit _meta.json payloads as JSON Lines to stdout.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_INTER_PAGE_SLEEP,
        help=f"Seconds between consecutive page fetches per company (default: {DEFAULT_INTER_PAGE_SLEEP}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N records.",
    )
    args = parser.parse_args(argv)

    records = _load_input(args.input)
    if args.limit is not None:
        records = records[: args.limit]

    status_counts: Counter[str] = Counter()
    for result in run(records, out_dir=args.out_dir, write=not args.dry_run, sleep=args.sleep):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))
        status = str(result.get("status", "unknown"))
        status_counts[status] += 1
        print(
            f"{result.get('name', '?')}: status={status} "
            f"pages={result.get('pages_collected', 0)}",
            file=sys.stderr,
        )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0


def _load_input(path: Path) -> list[dict]:
    if path.is_dir():
        records: list[dict] = []
        for entry in sorted(path.glob("*.json")):
            data = json.loads(entry.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records.append(data)
        return records
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return [raw]
    raise SystemExit(f"input {path} must be a JSON object or array")


if __name__ == "__main__":
    raise SystemExit(main())
