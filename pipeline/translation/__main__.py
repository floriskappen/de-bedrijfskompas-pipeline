"""CLI entry point: ``python -m pipeline.translation``."""

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

from .core import DEFAULT_SOURCE_DIRS, run
from .llm import TRANSLATION_TARGETS

DEFAULT_OUT_DIR = Path("data/translation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.translation",
        description="Translate English fields from analytic-stage outputs to Dutch.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company translation records (default: {DEFAULT_OUT_DIR}).",
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
        help="Process only the company with this id (filename stem in source dirs).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N companies.",
    )
    args = parser.parse_args(argv)

    companies = _discover_companies(company_filter=args.company)
    if args.limit is not None:
        companies = companies[: args.limit]

    status_counts: Counter[str] = Counter()
    for result in run(
        companies,
        out_dir=args.out_dir,
        write=not args.dry_run,
        offline=args.offline,
    ):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))
        status = str(result.get("status", "unknown"))
        status_counts[status] += 1
        print(
            f"{result.get('name', '?')}: status={status}",
            file=sys.stderr,
        )

    summary = ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items()))
    print(f"done: {summary}", file=sys.stderr)
    return 0


def _discover_companies(*, company_filter: str | None) -> list[tuple[str, str | None]]:
    """Collect unique company (name, website) pairs from all source-stage output dirs."""
    seen: dict[str, str | None] = {}  # company_id → (name, website)
    name_by_id: dict[str, str] = {}

    for stage_id, _ in TRANSLATION_TARGETS:
        src_dir = DEFAULT_SOURCE_DIRS.get(stage_id)
        if src_dir is None or not src_dir.exists():
            continue
        for record_path in sorted(src_dir.glob("*.json")):
            stem = record_path.stem
            if company_filter and stem != company_filter:
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
                seen[stem] = rec.get("website")

    return [(name_by_id[stem], seen[stem]) for stem in sorted(name_by_id)]


if __name__ == "__main__":
    raise SystemExit(main())
