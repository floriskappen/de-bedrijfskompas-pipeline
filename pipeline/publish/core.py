"""Manifest build, tag derivation, and GitHub Release upload.

The stage reads ``data/dataset-output/companies.json``, mints a ``manifest.json``
sidecar, and uploads both as assets on a fresh release of the pipeline repo via
the ``gh`` CLI. Tag and release name follow ISO 8601 UTC with ``:`` → ``-``
(e.g. ``2026-05-27T14-30-00Z``).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
DATA_FILE = Path("data/dataset-output/companies.json")


class PublishError(Exception):
    """Raised when the publish stage cannot proceed."""


@dataclass(frozen=True)
class PublishPlan:
    """Everything a release needs, computed before any upload."""

    tag: str
    manifest: dict
    data_path: Path


# ---------------------------------------------------------------------------
# Indirection points (overridable in tests)
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """Wall-clock UTC `now`, indirected so tests can freeze it."""
    return datetime.now(timezone.utc)


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PublishError(f"git rev-parse HEAD failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _check_gh_installed() -> None:
    if shutil.which("gh") is None:
        raise PublishError("`gh` CLI is not installed or not on PATH")


def _check_gh_authenticated() -> None:
    result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PublishError("`gh` CLI is not authenticated (run `gh auth login`)")


# ---------------------------------------------------------------------------
# Plan + publish
# ---------------------------------------------------------------------------


def _load_dataset(data_path: Path) -> list:
    if not data_path.exists():
        raise PublishError(f"input not found: {data_path}")
    try:
        payload = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublishError(f"input is not valid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise PublishError(f"input must be a JSON array, got {type(payload).__name__}")
    return payload


def build_plan(data_path: Path | None = None) -> PublishPlan:
    """Construct the release plan (tag + manifest) without touching the network."""

    path = data_path if data_path is not None else DATA_FILE
    payload = _load_dataset(path)
    now = _utcnow().astimezone(timezone.utc).replace(microsecond=0)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    tag = generated_at.replace(":", "-")
    manifest = {
        "generated_at": generated_at,
        "pipeline_git_sha": _git_sha(),
        "company_count": len(payload),
        "schema_version": SCHEMA_VERSION,
    }
    return PublishPlan(tag=tag, manifest=manifest, data_path=path)


def publish(*, data_path: Path | None = None, dry_run: bool = False) -> PublishPlan:
    """Publish ``companies.json`` + ``manifest.json`` as a GitHub Release.

    Order of operations is contract-relevant:

    1. Load + validate input (so a missing/malformed input fails *before* any
       ``gh`` call).
    2. Check ``gh`` is installed and authenticated (so we fail *before*
       generating the manifest if either is missing). Skipped in dry-run.
    3. Build the plan (tag + manifest).
    4. Write the manifest to a temp file and invoke ``gh release create``.

    Raises ``PublishError`` on any failure; returns the executed plan on success.
    """

    path = data_path if data_path is not None else DATA_FILE
    _load_dataset(path)  # validate before any gh / network interaction

    if not dry_run:
        _check_gh_installed()
        _check_gh_authenticated()

    plan = build_plan(path)

    if dry_run:
        import sys

        print(plan.tag, file=sys.stdout)
        print(json.dumps(plan.manifest, indent=2), file=sys.stdout)
        return plan

    notes = (
        f"{plan.manifest['company_count']} companies, "
        f"pipeline sha {plan.manifest['pipeline_git_sha']}"
    )

    with tempfile.TemporaryDirectory(prefix="dbk-publish-") as tmp:
        manifest_path = Path(tmp) / "manifest.json"
        manifest_path.write_text(
            json.dumps(plan.manifest, indent=2) + "\n", encoding="utf-8"
        )
        # gh attaches assets under their basename, so a temp parent dir is fine
        # as long as the file is literally named manifest.json (which it is).
        result = subprocess.run(
            [
                "gh",
                "release",
                "create",
                plan.tag,
                str(plan.data_path),
                str(manifest_path),
                "--title",
                plan.tag,
                "--notes",
                notes,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            if "already exists" in stderr.lower():
                raise PublishError(
                    f"tag {plan.tag} already exists (try again next second)"
                )
            raise PublishError(f"gh release create failed: {stderr}")

    return plan
