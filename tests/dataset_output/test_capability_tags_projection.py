"""Tests for capability tags projection in the dataset-output stage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.dataset_output.core import process
from pipeline.website_resolution import company_id


@pytest.fixture
def dirs(tmp_path: Path) -> dict[str, Path]:
    d = {
        "fact_dir": tmp_path / "fact-extraction",
        "geocoding_dir": tmp_path / "geocoding",
        "scoring_dir": tmp_path / "global-scoring",
        "tagline_dir": tmp_path / "tagline-extraction",
        "tagging_dir": tmp_path / "tagging",
        "translation_dir": tmp_path / "translation",
        "out_dir": tmp_path / "dataset-output",
    }
    for p in d.values():
        p.mkdir(parents=True, exist_ok=True)
    return d


def _write(path: Path, cid: str, payload: dict) -> None:
    (path / f"{cid}.json").write_text(json.dumps(payload), encoding="utf-8")


def _fact(name: str = "Acme B.V.", *, status: str = "ok") -> dict:
    return {"name": name, "website": "https://acme.example", "status": status}


def _proc(dirs: dict[str, Path], cid: str) -> dict:
    return process(
        cid,
        out_dir=dirs["out_dir"],
        write=False,
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )


def test_capability_tags_pass_through_verbatim(dirs: dict[str, Path]) -> None:
    """Scenario: Capability tags pass through verbatim."""
    cid = "acme"
    _write(dirs["fact_dir"], cid, _fact())
    tags = [
        {"family": "software-engineering", "prominence": "core"},
        {"family": "commercial", "prominence": "supporting"},
    ]
    _write(dirs["tagging_dir"], cid, {"name": "Acme B.V.", "status": "ok", "capability_tags": tags})

    rec = _proc(dirs, cid)
    assert rec["capability_tags"] == tags


def test_missing_tagging_nulls_block(dirs: dict[str, Path]) -> None:
    """Scenario: Missing source nulls the whole block."""
    cid = "acme"
    _write(dirs["fact_dir"], cid, _fact())
    # No tagging file written at all
    rec = _proc(dirs, cid)
    assert rec["capability_tags"] is None

    # Tagging file has non-ok status
    _write(dirs["tagging_dir"], cid, {"name": "Acme B.V.", "status": "upstream_failed", "capability_tags": None})
    rec = _proc(dirs, cid)
    assert rec["capability_tags"] is None


def test_empty_array_distinct_from_null(dirs: dict[str, Path]) -> None:
    """Scenario: Empty capability tags array is distinct from null."""
    cid = "acme"
    _write(dirs["fact_dir"], cid, _fact())
    _write(dirs["tagging_dir"], cid, {"name": "Acme B.V.", "status": "ok", "capability_tags": []})

    rec = _proc(dirs, cid)
    assert rec["capability_tags"] == []
