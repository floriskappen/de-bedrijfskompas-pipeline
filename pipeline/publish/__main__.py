"""CLI entry point: ``python -m pipeline.publish``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DATA_FILE, PublishError, publish


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.publish",
        description="Upload data/dataset-output/companies.json to a GitHub Release.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DATA_FILE,
        help=f"Path to companies.json (default: {DATA_FILE}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the manifest and tag, print to stdout; perform no upload, write no files.",
    )
    args = parser.parse_args(argv)

    try:
        publish(data_path=args.input, dry_run=args.dry_run)
    except PublishError as exc:
        print(f"publish failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
