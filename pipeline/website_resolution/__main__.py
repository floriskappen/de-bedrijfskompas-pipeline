"""CLI entry point: `python -m pipeline.website_resolution`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import run

DEFAULT_INPUT = Path("test-set/companies.json")
DEFAULT_OUT_DIR = Path("data/website-resolution")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.website_resolution",
        description=(
            "Resolve each company's canonical website URL. "
            "Skips records whose `website` field is already populated."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Path to the input JSON array (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Where to write per-company JSON outputs (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run all logic but write nothing to disk; emit outputs as JSON Lines to stdout.",
    )
    args = parser.parse_args(argv)

    records = _load_input(args.input)

    resolved = 0
    failed = 0
    skipped = 0

    for original, result in zip(records, run(records, write=not args.dry_run, out_dir=args.out_dir)):
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False))

        status = result.get("status")
        had_website = bool(original.get("website"))

        if status == "failed":
            failed += 1
        elif had_website:
            skipped += 1
        else:
            resolved += 1

    print(
        f"{resolved} resolved, {failed} failed, {skipped} skipped",
        file=sys.stderr,
    )
    return 0


def _load_input(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"input {path} must be a JSON array")
    return raw


if __name__ == "__main__":
    raise SystemExit(main())
