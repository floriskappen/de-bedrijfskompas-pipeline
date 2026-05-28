"""Tests for record status in the dataset-output stage."""

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


def test_capability_tags_alone_is_ok(dirs: dict[str, Path]) -> None:
    """Scenario: Capability tags alone is ok."""
    cid = "acme"
    _write(dirs["fact_dir"], cid, _fact())
    # No address, no latlng, no scores, no tagline
    # But has capability tags
    _write(dirs["tagging_dir"], cid, {
        "name": "Acme B.V.",
        "status": "ok",
        "capability_tags": [{"family": "software-engineering", "prominence": "core"}]
    })

    rec = _proc(dirs, cid)
    assert rec["status"] == "ok"
    assert rec["capability_tags"] == [{"family": "software-engineering", "prominence": "core"}]
    assert rec["address"] is None
    assert rec["latlng"] is None
    assert rec["scores"] is None
    assert rec["en"] is None
    assert rec["nl"] is None


def test_shell_company_with_no_tags_is_empty(dirs: dict[str, Path]) -> None:
    """Scenario: Shell company is empty."""
    cid = "acme"
    # Fact-extraction exists but status is empty/no data
    _write(dirs["fact_dir"], cid, _fact(status="empty"))
    # All other sources are absent or empty
    rec = _proc(dirs, cid)
    assert rec["status"] == "empty"
    assert rec["address"] is None
    assert rec["latlng"] is None
    assert rec["scores"] is None
    assert rec["en"] is None
    assert rec["nl"] is None
    assert rec["capability_tags"] is None
