"""Tests for the end-to-end orchestrator.

Each scenario in specs/pipeline-architecture/spec.md's two ADDED requirements
(End-to-End Orchestrator and Resume Semantics) maps to at least one named
test here; the mapping is recorded in the change's tasks.md.

Stages are replaced with recording fakes that also write a minimal valid
on-disk output, so downstream stages (and the orchestrator's --resume
existence checks) see the same shapes they would in a real run.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from pipeline import run as orch
from pipeline.website_resolution.core import company_id


# ---------------------------------------------------------------------------
# Fake-stage fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def seed() -> list[dict]:
    return [
        {"name": "Acme B.V.", "website": "https://acme.example"},
        {"name": "Foo B.V.", "website": "https://foo.example"},
    ]


@pytest.fixture
def fake_stages(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, list]]:
    """Replace every stage's run() with a recorder that writes plausible outputs.

    Returns a list of (stage_name, ids_or_records_seen) entries appended in
    call order, so tests can assert ordering and per-stage inputs.
    """

    call_log: list[tuple[str, list]] = []

    def _record_single_file(stage_name: str) -> callable:
        def fake_run(records, *, out_dir: Path, write: bool = True, **kwargs) -> Iterator[dict]:
            recs = list(records)
            seen_ids: list[str] = []
            out_dir.mkdir(parents=True, exist_ok=True)
            for rec in recs:
                name = rec.get("name") if isinstance(rec, dict) else None
                if not name:
                    continue
                cid = company_id(name)
                seen_ids.append(cid)
                if write:
                    (out_dir / f"{cid}.json").write_text(
                        json.dumps(
                            {
                                "name": name,
                                "website": rec.get("website", f"https://{cid}.example"),
                                "status": "ok",
                            }
                        ),
                        encoding="utf-8",
                    )
                yield {"company_id": cid, "name": name, "status": "ok"}

            call_log.append((stage_name, seen_ids))

        return fake_run

    def _record_subdir(stage_name: str) -> callable:
        def fake_run(records, *, out_dir: Path, write: bool = True, **kwargs) -> Iterator[dict]:
            recs = list(records)
            seen_ids: list[str] = []
            out_dir.mkdir(parents=True, exist_ok=True)
            for rec in recs:
                name = rec.get("name") if isinstance(rec, dict) else None
                if not name:
                    continue
                cid = company_id(name)
                seen_ids.append(cid)
                if write:
                    sub = out_dir / cid
                    sub.mkdir(parents=True, exist_ok=True)
                    (sub / "_meta.json").write_text(
                        json.dumps({"name": name, "website": rec.get("website"), "status": "ok"}),
                        encoding="utf-8",
                    )
                yield {"company_id": cid, "name": name, "status": "ok"}

            call_log.append((stage_name, seen_ids))

        return fake_run

    def _record_translation() -> callable:
        def fake_run(companies, *, out_dir: Path, write: bool = True, **kwargs) -> Iterator[dict]:
            pairs = list(companies)
            seen_ids: list[str] = []
            out_dir.mkdir(parents=True, exist_ok=True)
            for name, website in pairs:
                cid = company_id(name)
                seen_ids.append(cid)
                if write:
                    (out_dir / f"{cid}.json").write_text(
                        json.dumps(
                            {
                                "name": name,
                                "website": website,
                                "status": "ok",
                                "translations": {},
                            }
                        ),
                        encoding="utf-8",
                    )
                yield {"company_id": cid, "name": name, "status": "ok"}

            call_log.append(("translation", seen_ids))

        return fake_run

    def _record_dataset_output() -> callable:
        def fake_run(company_ids, *, out_dir: Path, write: bool = True, **kwargs) -> Iterator[dict]:
            ids = list(company_ids)
            out_dir.mkdir(parents=True, exist_ok=True)
            records = [{"company_id": cid, "name": cid, "status": "ok"} for cid in ids]
            if write:
                (out_dir / "companies.json").write_text(json.dumps(records), encoding="utf-8")
            call_log.append(("dataset-output", ids))
            for rec in records:
                yield rec

        return fake_run

    monkeypatch.setattr(
        "pipeline.website_resolution.core.run", _record_single_file("website-resolution")
    )
    monkeypatch.setattr(
        "pipeline.content_collection.core.run", _record_subdir("content-collection")
    )
    monkeypatch.setattr(
        "pipeline.fact_extraction.core.run", _record_single_file("fact-extraction")
    )
    def _record_dossier(stage_name: str) -> callable:
        def fake_run(records, *, out_dir: Path, write: bool = True, **kwargs) -> Iterator[dict]:
            recs = list(records)
            seen_ids: list[str] = []
            out_dir.mkdir(parents=True, exist_ok=True)
            for rec in recs:
                name = rec.get("name") if isinstance(rec, dict) else None
                if not name:
                    continue
                cid = company_id(name)
                seen_ids.append(cid)
                if write:
                    website = rec.get("website") or f"https://{cid}.example"
                    body = f"---\nname: {name}\nwebsite: {website}\n---\n\nDossier body.\n"
                    (out_dir / f"{cid}.md").write_text(body, encoding="utf-8")
                yield {"company_id": cid, "name": name, "status": "ok"}

            call_log.append((stage_name, seen_ids))

        return fake_run

    monkeypatch.setattr(
        "pipeline.content_summarization.core.run", _record_dossier("content-summarization")
    )
    monkeypatch.setattr("pipeline.geocoding.core.run", _record_single_file("geocoding"))
    monkeypatch.setattr(
        "pipeline.tagline_extraction.core.run", _record_single_file("tagline-extraction")
    )
    monkeypatch.setattr(
        "pipeline.global_scoring.core.run", _record_single_file("global-scoring")
    )
    monkeypatch.setattr("pipeline.translation.core.run", _record_translation())
    monkeypatch.setattr("pipeline.dataset_output.core.run", _record_dataset_output())

    return call_log


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_end_to_end_on_test_set(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: End-to-end run."""

    rc = orch.run_pipeline(seed, resume=False, publish=False, data_root=tmp_path)
    assert rc == 0
    assert (tmp_path / "dataset-output" / "companies.json").exists()
    stage_names = [name for name, _ in fake_stages]
    assert stage_names == [s[0] for s in orch.STAGES]


def test_run_calls_stages_in_process(
    tmp_path: Path, seed: list[dict], fake_stages, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Covers Scenario: Programmatic, not subprocess."""

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError(f"orchestrator must not subprocess: {args!r}")

    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(subprocess, "check_call", _boom)
    monkeypatch.setattr(subprocess, "check_output", _boom)

    rc = orch.run_pipeline(seed, resume=False, publish=False, data_root=tmp_path)
    assert rc == 0


def test_run_completes_stage_before_next(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: Stage ordering.

    Each stage's call_log entry is appended only after it has processed every
    company in its batch — so observing the entries in declared order is
    equivalent to observing that every stage completes before the next starts.
    """

    orch.run_pipeline(seed, resume=False, publish=False, data_root=tmp_path)
    observed = [name for name, _ in fake_stages]
    expected = [name for name, _ in orch.STAGES]
    assert observed == expected
    # Each stage saw both companies (no filtering)
    for name, ids in fake_stages:
        if name == "dataset-output":
            assert sorted(ids) == sorted({company_id(r["name"]) for r in seed})
        elif name == "translation":
            assert sorted(ids) == sorted({company_id(r["name"]) for r in seed})
        else:
            assert sorted(ids) == sorted({company_id(r["name"]) for r in seed})


def test_run_resume_skips_completed_pairs(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: Resume skips completed pairs."""

    acme_id = company_id("Acme B.V.")
    fact_dir = tmp_path / "fact-extraction"
    fact_dir.mkdir(parents=True, exist_ok=True)
    (fact_dir / f"{acme_id}.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok"}),
        encoding="utf-8",
    )

    orch.run_pipeline(seed, resume=True, publish=False, data_root=tmp_path)
    fact_call = next(ids for name, ids in fake_stages if name == "fact-extraction")
    assert acme_id not in fact_call
    assert company_id("Foo B.V.") in fact_call


def test_run_resume_still_runs_missing_stages(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: Resume still calls stages whose output is missing."""

    acme_id = company_id("Acme B.V.")
    fact_dir = tmp_path / "fact-extraction"
    fact_dir.mkdir(parents=True, exist_ok=True)
    (fact_dir / f"{acme_id}.json").write_text(
        json.dumps({"name": "Acme B.V.", "website": "https://acme.example", "status": "ok"}),
        encoding="utf-8",
    )
    # geocoding directory has no acme.json → geocoding must still run for acme

    orch.run_pipeline(seed, resume=True, publish=False, data_root=tmp_path)
    fact_call = next(ids for name, ids in fake_stages if name == "fact-extraction")
    geo_call = next(ids for name, ids in fake_stages if name == "geocoding")
    assert acme_id not in fact_call
    assert acme_id in geo_call


def test_run_default_reprocesses_everything(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: Default mode reprocesses everything."""

    # Pre-populate outputs for every single-file stage so --resume would skip
    acme_id = company_id("Acme B.V.")
    for stage in (
        "website-resolution",
        "fact-extraction",
        "content-summarization",
        "geocoding",
        "tagline-extraction",
        "global-scoring",
        "translation",
    ):
        d = tmp_path / stage
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{acme_id}.json").write_text(
            json.dumps({"name": "Acme B.V.", "status": "ok"}), encoding="utf-8"
        )
    sub = tmp_path / "content-collection" / acme_id
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "_meta.json").write_text(json.dumps({"name": "Acme B.V.", "status": "ok"}), encoding="utf-8")

    orch.run_pipeline(seed, resume=False, publish=False, data_root=tmp_path)
    # Without --resume every stage sees acme regardless of pre-existing output
    for name, ids in fake_stages:
        assert acme_id in ids, f"stage {name} unexpectedly skipped {acme_id}"


def test_run_subdirectory_stage_existence(
    tmp_path: Path, seed: list[dict], fake_stages: list[tuple[str, list]]
) -> None:
    """Covers Scenario: Subdirectory-stage existence (content-collection)."""

    acme_id = company_id("Acme B.V.")
    # Existence is keyed on <id>/_meta.json, NOT a top-level <id>.json
    bad_marker = tmp_path / "content-collection" / f"{acme_id}.json"
    bad_marker.parent.mkdir(parents=True, exist_ok=True)
    bad_marker.write_text("{}", encoding="utf-8")

    orch.run_pipeline(seed, resume=True, publish=False, data_root=tmp_path)
    cc_call = next(ids for name, ids in fake_stages if name == "content-collection")
    # The top-level <id>.json must NOT count as a completion marker
    assert acme_id in cc_call

    # Conversely, if we pre-create the real marker, content-collection skips it
    sub_dir = tmp_path / "content-collection" / acme_id
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "_meta.json").write_text(
        json.dumps({"name": "Acme B.V.", "status": "ok"}), encoding="utf-8"
    )
    fake_stages.clear()
    orch.run_pipeline(seed, resume=True, publish=False, data_root=tmp_path)
    cc_call = next(ids for name, ids in fake_stages if name == "content-collection")
    assert acme_id not in cc_call


def test_run_dossier_stage_existence(
    tmp_path: Path,
    seed: list[dict],
    fake_stages: list[tuple[str, list]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Dossier-stage existence (content-summarization)."""

    # content-summarization writes <id>.md dossiers. Pre-populate content-collection
    # so the upstream gate passes; pre-populate one .md so --resume skips that company.
    acme_id = company_id("Acme B.V.")
    foo_id = company_id("Foo B.V.")

    cc = tmp_path / "content-collection"
    for cid, name in [(acme_id, "Acme B.V."), (foo_id, "Foo B.V.")]:
        sub = cc / cid
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "_meta.json").write_text(
            json.dumps({"name": name, "status": "ok"}), encoding="utf-8"
        )

    cs = tmp_path / "content-summarization"
    cs.mkdir(parents=True, exist_ok=True)
    (cs / f"{acme_id}.md").write_text("---\nname: Acme B.V.\n---\nbody\n", encoding="utf-8")
    # A stray .json under content-summarization must NOT count as completion
    (cs / f"{foo_id}.json").write_text("{}", encoding="utf-8")

    # Replace content-summarization fake with a recorder that doesn't write —
    # we only care which companies it's invoked with.
    cs_calls: list[list[str]] = []

    def fake_cs_run(records, *, out_dir, write=True, **kwargs):  # noqa: ANN001
        recs = list(records)
        cs_calls.append([company_id(r["name"]) for r in recs if r.get("name")])
        if False:  # pragma: no cover — generator marker
            yield {}

    monkeypatch.setattr("pipeline.content_summarization.core.run", fake_cs_run)

    from pipeline.run import _drive_content_summarization

    _drive_content_summarization(resume=True, data_root=tmp_path)
    assert cs_calls == [[foo_id]]  # only foo runs; acme is skipped (has .md)


def test_run_publish_on_completion(
    tmp_path: Path,
    seed: list[dict],
    fake_stages: list[tuple[str, list]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Publish invoked on completion."""

    publish_calls: list[Path] = []

    def fake_publish(*, data_path: Path | None = None, dry_run: bool = False):
        publish_calls.append(data_path or Path("data/dataset-output/companies.json"))
        return None

    monkeypatch.setattr("pipeline.publish.core.publish", fake_publish)

    rc = orch.run_pipeline(seed, resume=False, publish=True, data_root=tmp_path)
    assert rc == 0
    assert publish_calls == [tmp_path / "dataset-output" / "companies.json"]
    # Publish ran after dataset-output, never before
    stage_names = [name for name, _ in fake_stages]
    assert stage_names[-1] == "dataset-output"


def test_run_publish_failure_exits_nonzero(
    tmp_path: Path,
    seed: list[dict],
    fake_stages: list[tuple[str, list]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers Scenario: Publish failure exits non-zero."""

    from pipeline.publish.core import PublishError

    def boom(*, data_path: Path | None = None, dry_run: bool = False):
        raise PublishError("simulated failure")

    monkeypatch.setattr("pipeline.publish.core.publish", boom)

    rc = orch.run_pipeline(seed, resume=False, publish=True, data_root=tmp_path)
    assert rc == 1
    # The dataset-output file was still produced by the upstream run
    assert (tmp_path / "dataset-output" / "companies.json").exists()
