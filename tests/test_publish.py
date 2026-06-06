"""Tests for the publish stage.

Each scenario in specs/publish/spec.md maps to at least one named test here;
the mapping is recorded in the change's tasks.md.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.publish import core as publish_core
from pipeline.publish.core import PublishError, build_plan, publish


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@pytest.fixture
def companies_file(tmp_path: Path) -> Path:
    """A minimal valid companies.json under a tmp data root."""
    data_dir = tmp_path / "dataset-output"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "companies.json"
    path.write_text(json.dumps([{"company_id": "a"}, {"company_id": "b"}]), encoding="utf-8")
    return path


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> datetime:
    instant = datetime(2026, 5, 27, 14, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(publish_core, "_utcnow", lambda: instant)
    return instant


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> str:
    sha = "a7ed347"
    monkeypatch.setattr(publish_core, "_git_sha", lambda: sha)
    return sha


@pytest.fixture
def gh_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_core.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    monkeypatch.setattr(publish_core, "_check_gh_authenticated", lambda: None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_publish_missing_input_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers Scenario: Missing input."""

    called: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: called.append(args[0]) or FakeProc()
    )

    with pytest.raises(PublishError, match="not found"):
        publish(data_path=tmp_path / "missing.json")
    # No gh CLI call attempted
    assert not any(cmd and cmd[0] == "gh" for cmd in called)


def test_publish_malformed_input_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers Scenario: Malformed input."""

    bad = tmp_path / "companies.json"
    bad.write_text("{not json", encoding="utf-8")
    called: list[list[str]] = []
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: called.append(args[0]) or FakeProc()
    )

    with pytest.raises(PublishError, match="not valid JSON"):
        publish(data_path=bad)
    assert not any(cmd and cmd[0] == "gh" for cmd in called)


def test_publish_manifest_shape(
    companies_file: Path, frozen_clock: datetime, fake_git: str
) -> None:
    """Covers Scenario: Manifest matches data."""

    plan = build_plan(companies_file)
    assert plan.manifest == {
        "generated_at": "2026-05-27T14:30:00Z",
        "pipeline_git_sha": fake_git,
        "company_count": 2,
        "schema_version": 2,
    }


def test_publish_release_tag_format(
    companies_file: Path,
    frozen_clock: datetime,
    fake_git: str,
    gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Standard release."""

    invocations: list[list[str]] = []

    def fake_subprocess_run(cmd, **kwargs):
        invocations.append(list(cmd))
        return FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    plan = publish(data_path=companies_file)
    assert plan.tag == "2026-05-27T14-30-00Z"

    gh_calls = [c for c in invocations if c and c[0] == "gh"]
    assert len(gh_calls) == 1
    cmd = gh_calls[0]
    assert cmd[:4] == ["gh", "release", "create", "2026-05-27T14-30-00Z"]
    assert str(companies_file) in cmd
    # Manifest asset is uploaded by a path that ends in /manifest.json — the
    # fixed asset filename gh sees and stores.
    assert any(arg.endswith("/manifest.json") for arg in cmd)
    assert "--title" in cmd
    assert cmd[cmd.index("--title") + 1] == "2026-05-27T14-30-00Z"


def test_publish_tag_collision_exits_nonzero(
    companies_file: Path,
    frozen_clock: datetime,
    fake_git: str,
    gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Tag collision."""

    def fake_subprocess_run(cmd, **kwargs):
        return FakeProc(returncode=1, stderr="release tag already exists")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    with pytest.raises(PublishError, match="already exists"):
        publish(data_path=companies_file)


def test_publish_gh_missing_exits_nonzero(
    companies_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers Scenario: gh not installed."""

    monkeypatch.setattr(publish_core.shutil, "which", lambda name: None)
    git_called = []
    monkeypatch.setattr(
        publish_core, "_git_sha", lambda: git_called.append(True) or "deadbeef"
    )

    with pytest.raises(PublishError, match="not installed"):
        publish(data_path=companies_file)
    # We failed before generating the manifest → git sha never queried
    assert git_called == []


def test_publish_gh_unauthenticated_exits_nonzero(
    companies_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers Scenario: gh not authenticated."""

    monkeypatch.setattr(publish_core.shutil, "which", lambda name: "/usr/bin/gh" if name == "gh" else None)
    original_bytes = companies_file.read_bytes()

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["gh", "auth"]:
            return FakeProc(returncode=1, stderr="not logged in")
        raise AssertionError(f"unexpected subprocess call: {cmd!r}")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    with pytest.raises(PublishError, match="not authenticated"):
        publish(data_path=companies_file)
    # companies.json is left untouched
    assert companies_file.read_bytes() == original_bytes


def test_publish_dry_run_no_side_effects(
    companies_file: Path,
    frozen_clock: datetime,
    fake_git: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Covers Scenario: Dry-run."""

    def fake_subprocess_run(cmd, **kwargs):
        raise AssertionError(f"dry-run must not invoke subprocesses: {cmd!r}")

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    # If which() were called for gh check, we'd fail the gh-installed guard;
    # dry-run skips that guard entirely. Sanity:
    monkeypatch.setattr(publish_core.shutil, "which", lambda name: None)

    files_before = sorted(p.name for p in companies_file.parent.iterdir())
    plan = publish(data_path=companies_file, dry_run=True)
    files_after = sorted(p.name for p in companies_file.parent.iterdir())
    assert files_before == files_after  # no manifest.json or anything new written

    out = capsys.readouterr().out
    assert "2026-05-27T14-30-00Z" in out
    assert '"generated_at": "2026-05-27T14:30:00Z"' in out
    assert '"company_count": 2' in out
    assert plan.tag == "2026-05-27T14-30-00Z"


def test_publish_standalone_invocation(
    companies_file: Path,
    frozen_clock: datetime,
    fake_git: str,
    gh_available: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Standalone invocation."""

    captured_cmds: list[list[str]] = []

    def fake_subprocess_run(cmd, **kwargs):
        captured_cmds.append(list(cmd))
        return FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    plan = publish(data_path=companies_file)
    assert plan.tag == "2026-05-27T14-30-00Z"
    gh_calls = [c for c in captured_cmds if c and c[0] == "gh"]
    assert len(gh_calls) == 1
    create = gh_calls[0]
    # Exactly two assets uploaded
    asset_args = [a for a in create[4:] if not a.startswith("--") and not a == "release"]
    # Walk: positional after `gh release create <tag>` until first '--'
    positional: list[str] = []
    for arg in create[4:]:
        if arg.startswith("--"):
            break
        positional.append(arg)
    assert len(positional) == 2
    assert str(companies_file) in positional
    assert any(p.endswith("/manifest.json") for p in positional)
