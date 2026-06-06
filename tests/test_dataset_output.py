"""Tests for the dataset-output stage.

Each scenario in specs/dataset-output/spec.md (and the relaxed pipeline-architecture
terminal-dependency scenario) maps to at least one named test here; the mapping is noted
in the change's tasks.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.dataset_output import core as dataset_output_core
from pipeline.dataset_output.core import AXES, process, run
from pipeline.dataset_output.timestamps import content_hash, timestamp_path
from pipeline.website_resolution import company_id


# ---------------------------------------------------------------------------
# Fixture helpers — write small source files across the four upstream dirs
# ---------------------------------------------------------------------------


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


def _fact(name: str = "Acme B.V.", *, address: dict | None = None, status: str = "regex_single", **extra) -> dict:
    rec = {"name": name, "website": "https://acme.example", "status": status}
    if address is not None:
        rec["address"] = address
    rec.update(extra)
    return rec


_ADDRESS = {"street": "Europalaan 100", "postcode": "3526 KS", "city": "Utrecht", "country": "NL"}


def _scoring(name: str = "Acme B.V.", *, power_no_signal: bool = False, status: str = "ok") -> dict:
    def axis(score, ev):
        return {"score": score, "evidence": ev, "reason": {"en": f"reason for {ev}"}}

    scores = {a: axis(60, "partial") for a in AXES}
    scores["substance"] = axis(70, "well_evidenced")
    if power_no_signal:
        scores["power"] = {"score": None, "evidence": "no_signal", "reason": {"en": "no signal"}}
    return {"name": name, "website": "https://acme.example", "status": status, "scores": scores}


def _tagline(name: str = "Acme B.V.", *, status: str = "ok", en: str | None = "Sells widgets.") -> dict:
    return {"name": name, "website": "https://acme.example", "status": status, "tagline": {"en": en}}


def _tagging(name: str = "Acme B.V.", *, status: str = "ok", tags: list[dict] | None = None) -> dict:
    if tags is None:
        tags = [
            {"isco_code": "251", "prominence": "core", "confidence": "high"},
            {"isco_code": "243", "prominence": "supporting", "confidence": "low"},
        ]
    return {"name": name, "website": "https://acme.example", "status": status, "capability_tags": tags}


def _translation(name: str = "Acme B.V.", *, status: str = "ok", include_tagline: bool = True, include_scores: bool = True) -> dict:
    translations: dict = {}
    if include_tagline:
        translations["tagline"] = {"nl": "Verkoopt widgets."}
    if include_scores:
        for a in AXES:
            translations[f"scores.{a}.reason"] = {"nl": f"reden voor {a}"}
    return {"name": name, "website": "https://acme.example", "status": status, "translations": translations}


def _full(dirs: dict[str, Path], cid: str = "acme", name: str = "Acme B.V.", **scoring_kw) -> None:
    _write(dirs["fact_dir"], cid, _fact(name, address=_ADDRESS))
    _write(dirs["geocoding_dir"], cid, {"name": name, "status": "ok", "latlng": {"lat": 52.0, "lng": 5.0}, "match_quality": "exact"})
    _write(dirs["scoring_dir"], cid, _scoring(name, **scoring_kw))
    _write(dirs["tagline_dir"], cid, _tagline(name))
    _write(dirs["tagging_dir"], cid, _tagging(name))
    _write(dirs["translation_dir"], cid, _translation(name))


def _proc(dirs: dict[str, Path], cid: str, *, write: bool = False) -> dict:
    return process(
        cid,
        out_dir=dirs["out_dir"],
        write=write,
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )


def _read_sidecar(dirs: dict[str, Path], cid: str) -> dict:
    return json.loads(timestamp_path(dirs["out_dir"], cid).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Input Sources
# ---------------------------------------------------------------------------


def test_pure_projection_no_model_calls(dirs, monkeypatch):
    """Input Sources / No model calls: processing makes no network/LLM call."""
    import pipeline.dataset_output.core as core

    # The module imports no llm client; assert that, and that a fully-offline run succeeds.
    assert not hasattr(core, "llm")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _full(dirs, "acme")
    rec = _proc(dirs, "acme")
    assert rec["status"] == "ok"


# ---------------------------------------------------------------------------
# Company Enumeration
# ---------------------------------------------------------------------------


def test_one_record_per_spine_file(dirs):
    """One record per fact-extraction file regardless of other sources."""
    _write(dirs["fact_dir"], "a", _fact("A B.V.", address=_ADDRESS))
    _write(dirs["fact_dir"], "b", _fact("B B.V."))
    _write(dirs["fact_dir"], "c", _fact("C B.V."))
    _write(dirs["scoring_dir"], "a", _scoring("A B.V."))  # only one has scoring
    records = list(
        run(["a", "b", "c"], out_dir=dirs["out_dir"], write=False,
            fact_dir=dirs["fact_dir"], scoring_dir=dirs["scoring_dir"],
            tagline_dir=dirs["tagline_dir"], tagging_dir=dirs["tagging_dir"],
            translation_dir=dirs["translation_dir"],
            geocoding_dir=dirs["geocoding_dir"])
    )
    assert {r["company_id"] for r in records} == {"a", "b", "c"}


def test_company_without_fact_extraction_skipped(dirs):
    """Company absent from the spine is not emitted (also covers pipeline-architecture
    'dataset output depends only on the fact-extraction spine')."""
    _write(dirs["scoring_dir"], "ghost", _scoring("Ghost B.V."))
    # Enumeration is driven by the fact-extraction dir, which has no 'ghost'.
    spine_ids = [p.stem for p in dirs["fact_dir"].glob("*.json")]
    assert "ghost" not in spine_ids
    # And processing a present company doesn't require scoring/tagline/translation to exist.
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    rec = _proc(dirs, "acme")
    assert rec["status"] == "ok"


# ---------------------------------------------------------------------------
# Output Record Shape
# ---------------------------------------------------------------------------


def test_fully_populated_record_includes_timestamps(dirs):
    """Fully populated record: all blocks present and well-formed."""
    _full(dirs, "acme", name="Acme B.V.")
    rec = _proc(dirs, "acme")
    assert rec["company_id"] == "acme" == company_id("Acme B.V.")
    assert rec["name"] == "Acme B.V." and rec["website"] == "https://acme.example"
    assert rec["status"] == "ok"
    assert rec["address"] == _ADDRESS
    assert rec["capability_tags"] == [
        {"isco_code": "251", "prominence": "core", "confidence": "high"},
        {"isco_code": "243", "prominence": "supporting", "confidence": "low"},
    ]
    assert rec["created_at"].endswith("Z")
    assert rec["updated_at"].endswith("Z")
    assert set(rec["scores"]) == set(AXES)
    assert rec["scores"]["substance"] == {"score": 70, "evidence": "well_evidenced"}
    for locale in ("en", "nl"):
        assert rec[locale]["tagline"]
        assert set(rec[locale]["scores"]) == set(AXES)
        assert rec[locale]["scores"]["substance"]["reason"]


def test_root_only_holds_timestamps(dirs):
    """Score numbers, evidence, address live at root only; never in locale trees."""
    _full(dirs, "acme")
    rec = _proc(dirs, "acme")
    for locale in ("en", "nl"):
        assert "address" not in rec[locale]
        assert "capability_tags" not in rec[locale]
        assert "created_at" not in rec[locale]
        assert "updated_at" not in rec[locale]
        for axis in AXES:
            assert set(rec[locale]["scores"][axis]) == {"reason"}  # no score/evidence


def test_first_time_seen_writes_sidecar_and_sets_both_timestamps(dirs):
    """First time a company is seen."""
    _full(dirs, "acme")
    rec = process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T10:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )

    assert rec["created_at"] == "2026-06-06T10:00:00Z"
    assert rec["updated_at"] == "2026-06-06T10:00:00Z"
    sidecar = _read_sidecar(dirs, "acme")
    assert sidecar == {
        "created_at": "2026-06-06T10:00:00Z",
        "updated_at": "2026-06-06T10:00:00Z",
        "content_hash": content_hash(rec),
    }


def test_unchanged_record_preserves_timestamps_and_does_not_rewrite_sidecar(dirs):
    """Unchanged record preserves both timestamps."""
    _full(dirs, "acme")
    first = process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T10:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )
    sidecar_path = timestamp_path(dirs["out_dir"], "acme")
    original_sidecar = sidecar_path.read_text(encoding="utf-8")

    second = process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T11:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )

    assert second["created_at"] == first["created_at"]
    assert second["updated_at"] == first["updated_at"]
    assert sidecar_path.read_text(encoding="utf-8") == original_sidecar


def test_changed_record_bumps_updated_at_only(dirs):
    """Changed record bumps updated_at only."""
    _full(dirs, "acme")
    process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T10:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )
    _write(dirs["tagline_dir"], "acme", _tagline("Acme B.V.", en="Builds better widgets."))

    rec = process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T11:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )

    assert rec["created_at"] == "2026-06-06T10:00:00Z"
    assert rec["updated_at"] == "2026-06-06T11:00:00Z"
    sidecar = _read_sidecar(dirs, "acme")
    assert sidecar["created_at"] == "2026-06-06T10:00:00Z"
    assert sidecar["updated_at"] == "2026-06-06T11:00:00Z"
    assert sidecar["content_hash"] == content_hash(rec)


def test_content_hash_ignores_timestamp_fields():
    """Hash excludes the timestamp fields."""
    base = {"company_id": "acme", "name": "Acme B.V.", "created_at": "2026-06-06T10:00:00Z"}
    changed_timestamps = {
        "company_id": "acme",
        "name": "Acme B.V.",
        "created_at": "2026-06-06T11:00:00Z",
        "updated_at": "2026-06-06T11:30:00Z",
    }
    changed_content = {"company_id": "acme", "name": "Acme Widgets B.V."}

    assert content_hash(base) == content_hash(changed_timestamps)
    assert content_hash(base) != content_hash(changed_content)


def test_single_run_shares_one_updated_at(dirs, monkeypatch):
    """Single run shares one timestamp."""
    _full(dirs, "acme")
    _full(dirs, "beta", name="Beta B.V.")
    calls = 0

    def sequential_timestamp() -> str:
        nonlocal calls
        calls += 1
        return f"2026-06-06T10:00:0{calls}Z"

    monkeypatch.setattr(dataset_output_core, "_run_timestamp", sequential_timestamp)
    records = list(run(
        ["acme", "beta"],
        out_dir=dirs["out_dir"],
        write=False,
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    ))

    assert calls == 1
    assert {record["updated_at"] for record in records} == {"2026-06-06T10:00:01Z"}


def test_dry_run_leaves_sidecars_untouched(dirs):
    """Dry-run does not write sidecars."""
    _full(dirs, "acme")
    _full(dirs, "beta", name="Beta B.V.")
    process(
        "acme",
        out_dir=dirs["out_dir"],
        write=True,
        run_timestamp="2026-06-06T10:00:00Z",
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )
    sidecar_path = timestamp_path(dirs["out_dir"], "acme")
    original_sidecar = sidecar_path.read_text(encoding="utf-8")
    _write(dirs["tagline_dir"], "acme", _tagline("Acme B.V.", en="Builds better widgets."))

    records = {record["company_id"]: record for record in run(
        ["acme", "beta"],
        out_dir=dirs["out_dir"],
        write=False,
        fact_dir=dirs["fact_dir"],
        scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"],
        tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"],
    )}

    assert records["acme"]["created_at"] == "2026-06-06T10:00:00Z"
    assert records["acme"]["updated_at"] != "2026-06-06T10:00:00Z"
    assert records["beta"]["created_at"] == records["beta"]["updated_at"]
    assert sidecar_path.read_text(encoding="utf-8") == original_sidecar
    assert not timestamp_path(dirs["out_dir"], "beta").exists()


# ---------------------------------------------------------------------------
# Field Projection
# ---------------------------------------------------------------------------


def test_nl_reason_flat_key_lookup(dirs):
    """Dutch reason resolved by flat dotted key from the translation file."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    _write(dirs["scoring_dir"], "acme", _scoring("Acme B.V."))
    _write(dirs["translation_dir"], "acme", {
        "name": "Acme B.V.", "status": "ok",
        "translations": {"scores.substance.reason": {"nl": "kern-reden"}},
    })
    rec = _proc(dirs, "acme")
    assert rec["nl"]["scores"]["substance"]["reason"] == "kern-reden"


# ---------------------------------------------------------------------------
# Block-Level Null Discipline
# ---------------------------------------------------------------------------


def test_missing_scoring_nulls_block(dirs):
    """Missing global-scoring nulls scores + each locale tree's scores; tagline/address unaffected."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    _write(dirs["tagline_dir"], "acme", _tagline("Acme B.V."))
    _write(dirs["translation_dir"], "acme", _translation("Acme B.V.", include_scores=False))
    rec = _proc(dirs, "acme")
    assert rec["scores"] is None
    assert rec["en"]["scores"] is None
    assert rec["nl"]["scores"] is None
    assert rec["en"]["tagline"] == "Sells widgets."
    assert rec["address"] == _ADDRESS


def test_no_signal_value_preserved(dirs):
    """Null value inside a present block survives (power no_signal)."""
    _full(dirs, "acme", power_no_signal=True)
    rec = _proc(dirs, "acme")
    assert rec["scores"] is not None
    assert rec["scores"]["power"] == {"score": None, "evidence": "no_signal"}


def test_partial_translation_mirrors_keys(dirs):
    """Partial translation: nl present, per-axis reasons filled, nl.tagline null (not omitted)."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    _write(dirs["scoring_dir"], "acme", _scoring("Acme B.V."))
    _write(dirs["tagline_dir"], "acme", _tagline("Acme B.V."))
    _write(dirs["translation_dir"], "acme", _translation("Acme B.V.", include_tagline=False))
    rec = _proc(dirs, "acme")
    assert rec["nl"] is not None
    assert "tagline" in rec["nl"] and rec["nl"]["tagline"] is None
    assert rec["nl"]["scores"]["substance"]["reason"]


# ---------------------------------------------------------------------------
# Record Status
# ---------------------------------------------------------------------------


def test_partial_company_status_ok(dirs):
    """Scores + tagline but no address → ok with address null."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V."))  # no address
    _write(dirs["scoring_dir"], "acme", _scoring("Acme B.V."))
    _write(dirs["tagline_dir"], "acme", _tagline("Acme B.V."))
    rec = _proc(dirs, "acme")
    assert rec["status"] == "ok"
    assert rec["address"] is None
    assert rec["scores"] is not None


def test_shell_company_status_empty(dirs):
    """Spine file present, no address/scores/tagline → empty, all payload blocks null."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", status="empty"))
    rec = _proc(dirs, "acme")
    assert rec["status"] == "empty"
    assert rec["address"] is None and rec["scores"] is None
    assert rec["en"] is None and rec["nl"] is None


def test_unreadable_spine_file_upstream_failed(dirs):
    """Corrupt fact-extraction file → upstream_failed."""
    (dirs["fact_dir"] / "acme.json").write_text("{not valid json", encoding="utf-8")
    rec = _proc(dirs, "acme")
    assert rec["status"] == "upstream_failed"
    assert rec["scores"] is None and rec["en"] is None


# ---------------------------------------------------------------------------
# Excluded Content
# ---------------------------------------------------------------------------


def test_excluded_content_dropped(dirs):
    """Internal artefacts (footer_text, urls_attempted, sitemap, model, upstream status) are dropped."""
    _write(dirs["fact_dir"], "acme", _fact(
        "Acme B.V.", address=_ADDRESS,
        footer_text="KVK 123...", urls_attempted=[{"url": "x"}],
        sitemap_consulted=True, sitemap_urls_found=500, pages={"index": {}},
    ))
    _write(dirs["scoring_dir"], "acme", _scoring("Acme B.V."))  # carries model/status internally
    rec = _proc(dirs, "acme")
    blob = json.dumps(rec)
    for forbidden in ("footer_text", "urls_attempted", "sitemap", "model", "regex_single", "pages"):
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# Output Layout and Execution Model
# ---------------------------------------------------------------------------


def test_cli_writes_aggregated_json(dirs):
    """write=True writes all company records to a single companies.json list file."""
    _full(dirs, "acme")
    _full(dirs, "beta", name="Beta B.V.")
    list(run(["acme", "beta"], out_dir=dirs["out_dir"], write=True,
             fact_dir=dirs["fact_dir"], scoring_dir=dirs["scoring_dir"],
             tagline_dir=dirs["tagline_dir"], tagging_dir=dirs["tagging_dir"],
             translation_dir=dirs["translation_dir"],
             geocoding_dir=dirs["geocoding_dir"]))
    out = dirs["out_dir"] / "companies.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert len(data) == 2
    assert {r["company_id"] for r in data} == {"acme", "beta"}


def test_dry_run_writes_nothing(dirs):
    """write=False yields records but creates no file."""
    _full(dirs, "acme")
    rec = _proc(dirs, "acme", write=False)
    assert rec["status"] == "ok"
    assert list(dirs["out_dir"].glob("*.json")) == []


def test_company_id_collision_raises(dirs):
    """Duplicate company IDs in the list passed to run/write raises a RuntimeError."""
    _full(dirs, "acme", name="Acme B.V.")
    # If we run with a duplicate company ID in the input list, it should raise.
    with pytest.raises(RuntimeError, match="collision"):
        list(run(["acme", "acme"], out_dir=dirs["out_dir"], write=True,
                 fact_dir=dirs["fact_dir"], scoring_dir=dirs["scoring_dir"],
                 tagline_dir=dirs["tagline_dir"], tagging_dir=dirs["tagging_dir"],
                 translation_dir=dirs["translation_dir"],
                 geocoding_dir=dirs["geocoding_dir"]))


def test_one_failure_does_not_abort_batch(dirs, monkeypatch):
    """One company raising mid-batch becomes upstream_failed; the rest still produce records."""
    _full(dirs, "good")
    _write(dirs["fact_dir"], "bad", _fact("Bad B.V.", address=_ADDRESS))

    real_process = process

    def flaky(cid, **kw):
        if cid == "bad":
            raise ValueError("boom")
        return real_process(cid, **kw)

    monkeypatch.setattr("pipeline.dataset_output.core.process", flaky)
    records = {r["company_id"]: r for r in run(
        ["good", "bad"], out_dir=dirs["out_dir"], write=False,
        fact_dir=dirs["fact_dir"], scoring_dir=dirs["scoring_dir"],
        tagline_dir=dirs["tagline_dir"], tagging_dir=dirs["tagging_dir"],
        translation_dir=dirs["translation_dir"],
        geocoding_dir=dirs["geocoding_dir"])}
    assert records["good"]["status"] == "ok"
    assert records["bad"]["status"] == "upstream_failed"


# ---------------------------------------------------------------------------
# Geocoding Integration Tests
# ---------------------------------------------------------------------------


def test_dataset_output_fully_populated_includes_latlng(dirs):
    """Scenario: Fully populated record."""
    _full(dirs, "acme", name="Acme B.V.")
    rec = _proc(dirs, "acme")
    assert rec["latlng"] == {"lat": 52.0, "lng": 5.0}
    assert rec["match_quality"] == "exact"


def test_dataset_output_latlng_match_quality_move_together(dirs):
    """Scenario: latlng and match_quality move together."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    _write(dirs["geocoding_dir"], "acme", {"name": "Acme B.V.", "status": "ok", "latlng": None, "match_quality": "exact"})
    rec = _proc(dirs, "acme")
    assert rec["latlng"] is None
    assert rec["match_quality"] is None


def test_dataset_output_geocoding_non_success_nulls_block(dirs):
    """Scenario: Geocoding non-success nulls the latlng block."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", address=_ADDRESS))
    _write(dirs["geocoding_dir"], "acme", {"name": "Acme B.V.", "status": "empty", "latlng": {"lat": 52.0, "lng": 5.0}, "match_quality": "exact"})
    rec = _proc(dirs, "acme")
    assert rec["latlng"] is None
    assert rec["match_quality"] is None


def test_dataset_output_latlng_alone_is_ok(dirs):
    """Scenario: Latlng alone is ok."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V."))
    _write(dirs["geocoding_dir"], "acme", {"name": "Acme B.V.", "status": "ok", "latlng": {"lat": 52.0, "lng": 5.0}, "match_quality": "exact"})
    rec = _proc(dirs, "acme")
    assert rec["status"] == "ok"
    assert rec["latlng"] == {"lat": 52.0, "lng": 5.0}
    assert rec["match_quality"] == "exact"


def test_dataset_output_shell_company_empty_with_latlng_null(dirs):
    """Scenario: Shell company is empty."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", status="empty"))
    _write(dirs["geocoding_dir"], "acme", {"name": "Acme B.V.", "status": "empty", "latlng": None, "match_quality": None})
    rec = _proc(dirs, "acme")
    assert rec["status"] == "empty"
    assert rec["latlng"] is None
    assert rec["match_quality"] is None


def test_dataset_output_includes_favicon_url(dirs):
    """Scenario: Fully populated record (verifying favicon_url)."""
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V.", favicon_url="https://acme.example/logo.png"))
    rec = _proc(dirs, "acme")
    assert rec["favicon_url"] == "https://acme.example/logo.png"

    # Verify that it is null if not provided
    _write(dirs["fact_dir"], "acme", _fact("Acme B.V."))
    rec = _proc(dirs, "acme")
    assert rec["favicon_url"] is None
